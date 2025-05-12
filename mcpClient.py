"""
Main MCP client implementation for SSE streaming and server proxy.
"""

import asyncio
import json
import logging
import signal
import sys
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict, List, Optional, Union

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from fastapi_mcp_client.config import MCPClientConfig
from fastapi_mcp_client.exceptions import MCPClientError, MCPConnectionError, MCPStreamError
from fastapi_mcp_client.utils import (
    create_mcp_initialize_payload,
    create_mcp_tool_call_payload,
    generate_request_id,
    parse_json_data,
    parse_sse_line,
)


# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("fastapi_mcp_client")


class MCPClient:
    """
    Client for interacting with FastAPI MCP-enabled APIs via Server-Sent Events (SSE).

    This client specializes in streaming operations through the Model Context Protocol
    over SSE. It handles the complete MCP session lifecycle:

    1. Establishing the SSE connection
    2. Extracting the session ID
    3. Initializing the MCP session
    4. Making tool calls
    5. Processing streaming responses

    The client supports both streaming and non-streaming operations, but is
    primarily designed for streaming use cases.
    """

    def __init__(
        self,
        base_url: str,
        config: Optional[MCPClientConfig] = None,
        log_level: Optional[str] = None,
    ):
        """
        Initialize the MCP client.

        Args:
            base_url: Base URL of the API (e.g., 'http://localhost:8000')
            config: Configuration options for the client. If None, uses default settings
            log_level: Override the logging level (e.g., 'DEBUG', 'INFO')
        """
        # Set the client configuration
        self.config = config or MCPClientConfig(base_url=base_url)

        # Set logging level
        if log_level:
            logger.setLevel(getattr(logging, log_level))
        else:
            logger.setLevel(getattr(logging, self.config.log_level))

        # HTTP clients
        self._async_client = httpx.AsyncClient(
            base_url=self.config.base_url, timeout=self.config.timeout
        )
        self._sync_client = httpx.Client(base_url=self.config.base_url, timeout=self.config.timeout)

        # Flag to track if MCP is available
        self._mcp_available = True

        logger.debug(f"MCPClient initialized with base URL: {base_url}")

    async def close(self) -> None:
        """Close the HTTP clients."""
        await self._async_client.aclose()
        self._sync_client.close()

    async def __aenter__(self) -> "MCPClient":
        """Async context manager entry."""
        return self

    async def __aexit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Async context manager exit."""
        await self.close()

    def __enter__(self) -> "MCPClient":
        """Sync context manager entry."""
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[Any],
    ) -> None:
        """Sync context manager exit."""
        self._sync_client.close()

    async def call_operation(
        self,
        operation_id: str,
        params: Optional[Dict[str, Any]] = None,
        stream: bool = False,
    ) -> Union[Dict[str, Any], AsyncIterator[Dict[str, Any]]]:
        """
        Call an operation via MCP.

        Args:
            operation_id: The operation to call
            params: Parameters for the operation
            stream: Whether to stream the response (via SSE)

        Returns:
            If stream=False, returns the operation result as a dictionary
            If stream=True, returns an async iterator yielding operation results

        Raises:
            MCPClientError: If the operation fails
        """
        if stream and self._mcp_available:
            try:
                # Return an async iterator for streaming results
                return self._stream_operation(operation_id, params)
            except Exception as e:
                logger.warning(f"MCP streaming failed: {e}")
                self._mcp_available = False
                # Fall back to non-streaming operation

        # Non-streaming operation or fallback
        result = await self._call_operation_direct(operation_id, params)

        # Return a single-item async iterator if streaming was requested
        if stream:

            async def _single_result_iterator() -> AsyncIterator[Dict[str, Any]]:
                yield result

            return _single_result_iterator()

        return result

    async def _stream_operation(
        self, operation_id: str, params: Optional[Dict[str, Any]] = None
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream operation results via MCP/SSE.

        Args:
            operation_id: The operation to call
            params: Parameters for the operation

        Returns:
            An async iterator yielding operation results

        Raises:
            MCPConnectionError: If connection to MCP server fails
            MCPStreamError: If streaming operation fails
        """
        # Generate request IDs
        request_id_initialize = generate_request_id()
        request_id_tool_call = generate_request_id()

        # Create payloads
        initialize_payload = create_mcp_initialize_payload(
            request_id_initialize, self.config.client_info, self.config.protocol_version
        )

        tool_call_payload = create_mcp_tool_call_payload(request_id_tool_call, operation_id, params)

        # Event tracking
        session_id = None
        message_queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        session_id_found = asyncio.Event()

        try:
            # Establish SSE connection
            logger.debug(f"Establishing SSE connection to {self.config.full_connection_url}")

            async with self._async_client.stream(
                "GET",
                self.config.connection_path,
                headers={"Accept": "text/event-stream", **self.config.default_headers},
            ) as response:
                if response.status_code != 200:
                    raise MCPConnectionError(
                        f"Failed to connect to MCP server: {response.status_code}"
                    )

                # Start a background task to read from the SSE stream
                async def read_sse_stream() -> None:
                    nonlocal session_id
                    first_data_event = True
                    buffer = ""

                    try:
                        async for line in response.aiter_lines():
                            line = line.strip()

                            # Empty line marks the end of an event
                            if not line:
                                if buffer:
                                    event_data = buffer
                                    buffer = ""

                                    # Check for session ID in the first event
                                    if first_data_event:
                                        first_data_event = False

                                        # Check for session_id in URL format
                                        if event_data.startswith(self.config.messages_path):
                                            try:
                                                # Extract session_id from query string
                                                if "?session_id=" in event_data:
                                                    session_id = event_data.split("?session_id=")[
                                                        1
                                                    ].split("&")[0]
                                                    logger.debug(
                                                        f"Found session_id in event data: {session_id}"
                                                    )
                                                    session_id_found.set()
                                                    continue
                                            except Exception as e:
                                                logger.warning(
                                                    f"Error extracting session_id from event data: {e}"
                                                )

                                    # Process the event data
                                    try:
                                        message = parse_json_data(event_data)

                                        # Convert message to dict if it's not already
                                        if not isinstance(message, dict):
                                            if isinstance(message, list):
                                                message = {"data": message}
                                            else:
                                                message = {"data": str(message)}

                                        # Check for session_id in message
                                        if not session_id and "session_id" in message:
                                            session_id = message["session_id"]
                                            logger.debug(
                                                f"Found session_id in message: {session_id}"
                                            )
                                            session_id_found.set()

                                        await message_queue.put(message)
                                    except Exception as e:
                                        logger.warning(f"Error processing event data: {e}")
                                        await message_queue.put({"error": str(e)})

                                continue

                            # Parse SSE line
                            parsed = parse_sse_line(line)
                            if not parsed:
                                continue

                            # Check for session_id in "id:" field
                            if parsed["field"] == "id" and not session_id:
                                session_id = parsed["value"]
                                logger.debug(f"Found session_id in id field: {session_id}")
                                session_id_found.set()

                            # Accumulate data fields
                            if parsed["field"] == "data":
                                buffer += parsed["value"]

                    except Exception as e:
                        logger.error(f"Error reading SSE stream: {e}")
                        await message_queue.put({"error": f"SSE stream error: {str(e)}"})
                    finally:
                        # Signal end of stream
                        await message_queue.put({"done": True})
                        # Ensure session_id_found is set to avoid blocking
                        if not session_id_found.is_set():
                            session_id_found.set()

                # Start the reader task
                asyncio.create_task(read_sse_stream())

                # Wait for session ID with timeout
                try:
                    await asyncio.wait_for(session_id_found.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    raise MCPConnectionError("Timeout waiting for session ID")

                if not session_id:
                    # Check header as last resort
                    session_id = response.headers.get("X-MCP-Session-ID")
                    if not session_id:
                        raise MCPConnectionError("Failed to obtain session ID")

                # Send initialize request
                messages_url = f"{self.config.full_messages_url}?session_id={session_id}"
                logger.debug(f"Sending initialize request to {messages_url}")

                init_response = await self._async_client.post(
                    messages_url,
                    json=initialize_payload,
                    headers={"Content-Type": "application/json", **self.config.default_headers},
                )
                init_response.raise_for_status()

                # Send tool call request
                logger.debug(f"Sending tool call request to {messages_url}")
                tool_call_response = await self._async_client.post(
                    messages_url,
                    json=tool_call_payload,
                    headers={"Content-Type": "application/json", **self.config.default_headers},
                )
                tool_call_response.raise_for_status()

                # Yield messages from the queue
                while True:
                    message = await message_queue.get()
                    if message.get("done", False):  # End of stream
                        break
                    if "error" in message:
                        raise MCPStreamError(message["error"])
                    yield message

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error during MCP operation: {e}")
            raise MCPConnectionError(f"HTTP error: {e.response.status_code}")
        except (httpx.RequestError, asyncio.TimeoutError) as e:
            logger.error(f"Connection error during MCP operation: {e}")
            raise MCPConnectionError(f"Connection error: {str(e)}")
        except Exception as e:
            logger.error(f"Error during MCP operation: {e}")
            raise MCPClientError(f"MCP operation failed: {str(e)}")

    async def _call_operation_direct(
        self, operation_id: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Call an operation directly via HTTP (non-streaming).

        Args:
            operation_id: The operation to call
            params: Parameters for the operation

        Returns:
            The operation result as a dictionary

        Raises:
            MCPClientError: If the operation fails
        """
        try:
            # Determine the HTTP method, path, and data transformation for the operation
            method, path, data = self._get_operation_details(operation_id, params)

            logger.debug(f"Calling operation {operation_id} via HTTP {method} to {path}")

            # Make the HTTP request
            response = await self._async_client.request(
                method,
                path,
                json=data if method in ("POST", "PUT", "PATCH") else None,
                params=data if method in ("GET", "DELETE") else None,
                headers=self.config.default_headers,
            )
            response.raise_for_status()

            # Parse the response
            if response.status_code == 204:  # No Content
                return {}

            try:
                result: Dict[str, Any] = response.json()
                return result
            except json.JSONDecodeError:
                logger.warning(f"Response is not valid JSON: {response.text}")
                return {"text": response.text}

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error during {operation_id} operation: {e}")
            error_msg = f"HTTP error: {e.response.status_code}"
            try:
                error_details = e.response.json()
                if "detail" in error_details:
                    error_msg = f"HTTP error: {e.response.status_code} - {error_details['detail']}"
            except Exception:
                pass

            raise MCPClientError(error_msg)
        except Exception as e:
            logger.error(f"Error during {operation_id} operation: {e}")
            raise MCPClientError(f"Operation {operation_id} failed: {str(e)}")

    def _get_operation_details(
        self, operation_id: str, params: Optional[Dict[str, Any]] = None
    ) -> tuple[str, str, Optional[Dict[str, Any]]]:
        """
        Get the HTTP method, path, and transformed parameters for an operation.

        Args:
            operation_id: The operation to call
            params: Parameters for the operation

        Returns:
            Tuple of (HTTP method, path, transformed parameters)

        Raises:
            MCPClientError: If the operation is unknown
        """
        # This method maps operation IDs to HTTP endpoints
        # It can be extended with more operations as needed

        operation_details = {
            # Example mapping for some common operations
            "health_check": ("GET", "/health", None),
            "ground_query": ("POST", "/ground", None),
            "ingest_content": ("POST", "/ingest", None),
        }

        # Allow custom operations to be specified directly
        if ":" in operation_id:
            parts = operation_id.split(":", 1)
            if len(parts) == 2:
                method, path = parts
                return method.upper(), path, params

        # Check if operation is in the predefined mappings
        if operation_id in operation_details:
            method, path, param_transform = operation_details[operation_id]

            # Transform parameters if a transform function is provided
            transformed_params = params
            if param_transform is not None and params is not None:
                transformed_params = param_transform(params)

            return method, path, transformed_params

        # Default to a direct API call
        # This assumes the operation_id maps directly to an API endpoint
        return "POST", f"/{operation_id}", params


# Pydantic models for API requests and responses
class OperationRequest(BaseModel):
    operation_id: str
    params: Optional[Dict[str, Any]] = None
    stream: bool = False


class OperationResponse(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None


# Global client instance
mcp_client: Optional[MCPClient] = None
shutdown_event = asyncio.Event()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the lifecycle of the MCPClient.
    
    Creates a global client instance when the app starts and 
    closes it when the app shuts down.
    """
    global mcp_client, shutdown_event
    
    # Get settings from environment or config
    mcp_server_url = app.state.mcp_server_url
    
    # Create client
    mcp_client = MCPClient(base_url=mcp_server_url)
    
    # Check if MCP server is available
    try:
        await mcp_client.call_operation("health_check")
        logger.info(f"Successfully connected to MCP server at {mcp_server_url}")
    except Exception as e:
        logger.warning(f"Unable to verify MCP server at {mcp_server_url}: {e}")
    
    # Start the app
    yield
    
    # Clean up
    if mcp_client:
        await mcp_client.close()
    
    shutdown_event.set()
    logger.info("MCPClient proxy server shutdown complete")


# Create FastAPI app instance
app = FastAPI(
    title="MCP Client Proxy Server",
    description="Proxy server for MCP operations",
    version="0.1.0",
    lifespan=lifespan,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust this in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint for the proxy server."""
    if not mcp_client:
        raise HTTPException(status_code=503, detail="MCP client not initialized")
    
    try:
        # Check MCP server health
        result = await mcp_client.call_operation("health_check")
        return {
            "status": "ok",
            "mcp_server": {
                "status": "ok",
                "details": result
            }
        }
    except Exception as e:
        return {
            "status": "ok",
            "mcp_server": {
                "status": "error",
                "error": str(e)
            }
        }


@app.post("/operation", response_model=OperationResponse)
async def call_operation(request: OperationRequest):
    """
    Call an MCP operation.
    
    Args:
        request: The operation request containing operation_id, params, and stream flag
        
    Returns:
        The operation result
    """
    if not mcp_client:
        raise HTTPException(status_code=503, detail="MCP client not initialized")
    
    # Non-streaming operations
    if not request.stream:
        try:
            result = await mcp_client.call_operation(
                request.operation_id, 
                request.params
            )
            return OperationResponse(success=True, data=result)
        except MCPClientError as e:
            return OperationResponse(success=False, error=str(e))
    
    # For streaming operations, return a streaming response
    # This is handled by a different endpoint
    return OperationResponse(
        success=False, 
        error="Streaming operations should use the /operation/stream endpoint"
    )


@app.post("/operation/stream")
async def stream_operation(request: OperationRequest):
    """
    Stream an MCP operation.
    
    Args:
        request: The operation request containing operation_id, params, and stream flag
        
    Returns:
        A streaming response with operation results
    """
    if not mcp_client:
        raise HTTPException(status_code=503, detail="MCP client not initialized")
    
    # If stream is not requested, redirect to non-streaming endpoint
    if not request.stream:
        try:
            result = await mcp_client.call_operation(
                request.operation_id, 
                request.params
            )
            return JSONResponse(content={"success": True, "data": result})
        except MCPClientError as e:
            return JSONResponse(
                content={"success": False, "error": str(e)},
                status_code=500
            )
    
    # Stream the response
    async def generate_stream():
        request_id = str(uuid.uuid4())
        try:
            # Begin the streaming response
            yield json.dumps({"request_id": request_id, "event": "start"}).encode() + b"\n"
            
            # Stream the operation results
            async for message in await mcp_client.call_operation(
                request.operation_id, 
                request.params, 
                stream=True
            ):
                yield json.dumps({
                    "request_id": request_id,
                    "event": "data",
                    "data": message
                }).encode() + b"\n"
                
            # End the stream
            yield json.dumps({"request_id": request_id, "event": "end"}).encode() + b"\n"
            
        except Exception as e:
            # Send error message
            yield json.dumps({
                "request_id": request_id,
                "event": "error",
                "error": str(e)
            }).encode() + b"\n"
    
    # Return a streaming response
    return StreamingResponse(
        generate_stream(),
        media_type="application/json",
        headers={"X-Content-Type-Options": "nosniff"}
    )


async def test_client(base_url: str = "http://localhost:8000"):
    """Test the MCP client with a simple operation."""
    print("Starting MCPClient test...")
    
    try:
        # Create the client
        async with MCPClient(base_url) as client:
            # Try a health check operation
            print("Calling health_check operation...")
            try:
                result = await client.call_operation("health_check")
                print(f"Health check result: {result}")
            except MCPClientError as e:
                print(f"Health check failed: {e}")
            
            # Try a direct operation
            print("\nCalling a direct operation...")
            try:
                result = await client.call_operation("GET:/ping")
                print(f"Ping result: {result}")
            except MCPClientError as e:
                print(f"Ping operation failed: {e}")
            
            # Try a streaming operation
            print("\nTrying a streaming operation...")
            try:
                async for message in await client.call_operation("ground_query", {"query": "test query"}, stream=True):
                    print(f"Received message: {message}")
            except MCPClientError as e:
                print(f"Streaming operation failed: {e}")
                
    except Exception as e:
        print(f"Error testing client: {e}")


async def run_perpetual_client(base_url: str = "http://localhost:8000", health_check_interval: int = 30):
    """
    Run the MCP client in a perpetual loop that keeps reconnecting.
    
    Args:
        base_url: Base URL of the API
        health_check_interval: Interval in seconds between health checks
    """
    print(f"Starting MCPClient in perpetual mode, connecting to {base_url}")
    print("Press Ctrl+C to exit")
    
    # Signal handler for graceful shutdown
    shutdown_event = asyncio.Event()
    
    def signal_handler():
        print("\nShutdown signal received, gracefully shutting down...")
        shutdown_event.set()
    
    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    # Retry settings
    max_retry_delay = 60  # Maximum delay between retries in seconds
    retry_delay = 5  # Initial delay between retries in seconds
    
    connection_attempt = 0
    
    while not shutdown_event.is_set():
        connection_attempt += 1
        print(f"\nConnection attempt #{connection_attempt}")
        
        try:
            # Create the client
            async with MCPClient(base_url) as client:
                print(f"Connected to MCP server at {base_url}")
                
                # Reset retry delay on successful connection
                retry_delay = 5
                
                # Keep running until shutdown signal or error
                while not shutdown_event.is_set():
                    try:
                        # Periodic health check to verify connection
                        print(f"\nPerforming health check ({time.strftime('%H:%M:%S')})")
                        result = await client.call_operation("health_check")
                        print(f"Server is healthy: {result}")
                        
                        # Maintain an active connection by initializing MCP session
                        try:
                            init_result = await client.call_operation("mcp.initialize", {})
                            print(f"MCP session active: {init_result}")
                        except MCPClientError as e:
                            # Non-fatal error, log and continue
                            print(f"MCP session check failed: {e}")
                        
                        # Wait for next health check or shutdown
                        try:
                            await asyncio.wait_for(shutdown_event.wait(), timeout=health_check_interval)
                        except asyncio.TimeoutError:
                            # Timeout is expected, just continue with next health check
                            pass
                            
                    except MCPClientError as e:
                        print(f"Health check failed: {e}")
                        # Break inner loop to reconnect
                        break
                    except Exception as e:
                        print(f"Unexpected error during health check: {e}")
                        # Break inner loop to reconnect
                        break
                
        except Exception as e:
            if shutdown_event.is_set():
                # If we're shutting down, don't report the error or retry
                break
                
            print(f"Connection error: {e}")
            
            # Implement exponential backoff for retries
            print(f"Retrying in {retry_delay} seconds...")
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=retry_delay)
            except asyncio.TimeoutError:
                # Timeout is expected, continue with retry
                pass
            
            # Increase retry delay for next attempt (exponential backoff)
            retry_delay = min(retry_delay * 1.5, max_retry_delay)
    
    print("MCPClient perpetual mode terminated")


async def run_stdio_client(base_url: str = "http://localhost:8000"):
    """
    Run the MCP client as a stdio interface.
    
    This mode reads JSON requests from stdin, processes them using the
    MCPClient, and writes JSON responses to stdout. It's designed for
    use in scripts or when piping between processes.
    
    Args:
        base_url: Base URL of the MCP server
    """
    print(f"Starting MCPClient in stdio mode, connecting to {base_url}", file=sys.stderr)
    print("Send JSON requests on stdin, one per line. Press Ctrl+D to exit.", file=sys.stderr)
    print("Format: {'operation_id': 'operation_name', 'params': {}, 'stream': false}", file=sys.stderr)
    
    # Create a singleton client
    async with MCPClient(base_url) as client:
        # Set up signal handling for clean shutdown
        shutdown_event = asyncio.Event()
        
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, shutdown_event.set)
        
        # Create a queue for stdin lines
        line_queue: asyncio.Queue[str] = asyncio.Queue()
        
        # Read lines from stdin in a separate thread to avoid blocking
        def stdin_reader():
            try:
                for line in sys.stdin:
                    asyncio.run_coroutine_threadsafe(line_queue.put(line.strip()), loop)
            except Exception as e:
                logger.error(f"Error reading from stdin: {e}")
            finally:
                # EOF or error, signal end
                asyncio.run_coroutine_threadsafe(shutdown_event.set(), loop)
        
        # Start the stdin reader thread
        import threading
        reader_thread = threading.Thread(target=stdin_reader, daemon=True)
        reader_thread.start()
        
        # Process requests until shutdown
        while not shutdown_event.is_set():
            # Get the next line or wait for shutdown
            try:
                # Use a timeout to periodically check shutdown_event
                line = await asyncio.wait_for(line_queue.get(), timeout=0.1)
            except asyncio.TimeoutError:
                # Check if shutdown was requested
                continue
            
            # Skip empty lines
            if not line:
                continue
            
            # Process the request
            try:
                # Parse the JSON request
                request_data = json.loads(line)
                request_id = request_data.get("request_id", str(uuid.uuid4()))
                operation_id = request_data.get("operation_id")
                params = request_data.get("params")
                stream = request_data.get("stream", False)
                
                if not operation_id:
                    # Invalid request
                    response = {
                        "request_id": request_id,
                        "success": False,
                        "error": "Missing required field: operation_id"
                    }
                    print(json.dumps(response), flush=True)
                    continue
                
                # Process the operation
                if not stream:
                    # Non-streaming operation
                    try:
                        result = await client.call_operation(operation_id, params)
                        response = {
                            "request_id": request_id,
                            "success": True,
                            "data": result
                        }
                    except Exception as e:
                        response = {
                            "request_id": request_id,
                            "success": False,
                            "error": str(e)
                        }
                    
                    # Send the response
                    print(json.dumps(response), flush=True)
                else:
                    # Streaming operation
                    try:
                        # Send start event
                        print(json.dumps({
                            "request_id": request_id,
                            "event": "start"
                        }), flush=True)
                        
                        # Stream results
                        async for message in await client.call_operation(operation_id, params, stream=True):
                            print(json.dumps({
                                "request_id": request_id,
                                "event": "data",
                                "data": message
                            }), flush=True)
                        
                        # Send end event
                        print(json.dumps({
                            "request_id": request_id,
                            "event": "end"
                        }), flush=True)
                    except Exception as e:
                        # Send error event
                        print(json.dumps({
                            "request_id": request_id,
                            "event": "error",
                            "error": str(e)
                        }), flush=True)
            
            except json.JSONDecodeError:
                # Invalid JSON
                response = {
                    "request_id": str(uuid.uuid4()),
                    "success": False,
                    "error": "Invalid JSON request"
                }
                print(json.dumps(response), flush=True)
            except Exception as e:
                # Unexpected error
                response = {
                    "request_id": str(uuid.uuid4()),
                    "success": False,
                    "error": f"Error processing request: {str(e)}"
                }
                print(json.dumps(response), flush=True)
    
    # Cleanup
    print("MCPClient stdio mode terminated", file=sys.stderr)


def run_server(host: str = "0.0.0.0", port: int = 8080, mcp_server_url: str = "http://localhost:8000"):
    """
    Run the FastAPI server.
    
    Args:
        host: The host to bind to
        port: The port to listen on
        mcp_server_url: The URL of the MCP server to connect to
    """
    # Set MCP server URL in application state
    app.state.mcp_server_url = mcp_server_url
    
    # Run the server
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    # Parse command line arguments
    import argparse
    
    parser = argparse.ArgumentParser(description="MCP Client")
    parser.add_argument("--mode", choices=["server", "client", "perpetual", "stdio"], default="server",
                        help="Run mode: server (proxy server), client (single test), perpetual (long-running client), stdio (stdin/stdout interface)")
    parser.add_argument("--mcp-url", default="http://localhost:8000", 
                        help="MCP server URL")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Host to bind server to (server mode only)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Port to listen on (server mode only)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                        help="Logging level")
    
    args = parser.parse_args()
    
    # Set logging level
    logging.getLogger("fastapi_mcp_client").setLevel(getattr(logging, args.log_level))
    
    # Run in the selected mode
    if args.mode == "client":
        # Run a single test
        print(f"Running client test against MCP server at {args.mcp_url}")
        asyncio.run(test_client(args.mcp_url))
        print("Test completed")
    elif args.mode == "perpetual":
        # Run in perpetual mode
        try:
            print(f"Running in perpetual mode, connecting to {args.mcp_url}")
            asyncio.run(run_perpetual_client(args.mcp_url))
        except KeyboardInterrupt:
            print("\nExiting due to user interrupt")
    elif args.mode == "stdio":
        # Run in stdio mode
        try:
            print(f"Running in stdio mode, connecting to {args.mcp_url}", file=sys.stderr)
            # Redirect logging to stderr
            logging.basicConfig(stream=sys.stderr, level=getattr(logging, args.log_level))
            asyncio.run(run_stdio_client(args.mcp_url))
        except KeyboardInterrupt:
            print("\nExiting due to user interrupt", file=sys.stderr)
    elif args.mode == "server":
        # Run as a server
        print(f"Starting MCP proxy server on {args.host}:{args.port}, connecting to {args.mcp_url}")
        run_server(args.host, args.port, args.mcp_url)
    else:
        print(f"Unknown mode: {args.mode}")
        sys.exit(1) 
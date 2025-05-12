# MCP Client

This package provides client implementations for interacting with MCP (Modular Capability Provider) servers through various interfaces:

- HTTP-based client for standard REST MCP servers
- stdio-based client for command-line based MCP servers
- SSE-based client for server-sent events based MCP servers

## Features

- Multiple client types for different MCP server implementations
- Factory pattern for easily creating clients based on server type
- Integration with Claude LLM for handling natural language queries
- Tool invocation and result handling
- Conversation logging

## Installation

Make sure you have the required dependencies:

```bash
pip install aiohttp anthropic mcp
```

## Usage

### Basic Client Examples

```python
import asyncio
from http_mcp_client import HttpMCPClient
from mcp_client import MCPClient
from sse_mcp_client import SSEMCPClient

async def main():
    # Create and connect an HTTP client
    http_client = HttpMCPClient(server_url="http://localhost:8001/mcp")
    await http_client.connect()
    
    # Create and connect a stdio client
    stdio_client = MCPClient()
    await stdio_client.connect_to_server("server.py")
    
    # Create and connect an SSE client
    sse_client = SSEMCPClient(server_url="http://localhost:8001/mcp")
    await sse_client.connect()
    
    # Process a query with each client
    http_messages = await http_client.process_query("What HTTP tools are available?")
    stdio_messages = await stdio_client.process_query("What stdio tools are available?")
    sse_messages = await sse_client.process_query("What SSE tools are available?")
    
    # Clean up
    await http_client.cleanup()
    await stdio_client.cleanup()
    await sse_client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
```

### Using the Client Factory

The client factory makes it easy to create different types of clients:

```python
import asyncio
from mcp_client_factory import MCPClientFactory

async def main():
    # Create an HTTP client
    http_client = await MCPClientFactory.create_client(
        client_type="http",
        server_url="http://localhost:8001/mcp"
    )
    
    # Create a stdio client
    stdio_client = await MCPClientFactory.create_client(
        client_type="stdio",
        server_script_path="server.py"
    )
    
    # Create an SSE client
    sse_client = await MCPClientFactory.create_client(
        client_type="sse",
        server_url="http://localhost:8001/mcp"
    )
    
    # Create a client from environment variables
    env_client = await MCPClientFactory.create_from_env()
    
    # Don't forget to clean up
    await http_client.cleanup()
    await stdio_client.cleanup()
    await sse_client.cleanup()
    await env_client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
```

## Command Line Tools

### Basic HTTP Client Example

```bash
python example_usage.py "What tools are available?"
```

### All Client Types Example

```bash
# Use HTTP client (default)
python example_all_clients.py --client-type http --server-url http://localhost:8001/mcp "What tools are available?"

# Use stdio client
python example_all_clients.py --client-type stdio --server-script server.py "What tools are available?"

# Use SSE client
python example_all_clients.py --client-type sse --server-url http://localhost:8001/mcp "What tools are available?"
```

### Advanced Example with Configuration Options

```bash
# Use configuration from environment variables
python advanced_example.py --env "What tools are available?"

# Use configuration from a JSON file
python advanced_example.py --config client_config.json "What tools are available?"
```

## Environment Variables

The following environment variables can be used to configure the client:

- `MCP_CLIENT_TYPE`: Type of client to create ("http", "stdio", or "sse")
- `MCP_SERVER_URL`: URL of the HTTP or SSE MCP server
- `MCP_SERVER_SCRIPT`: Path to the server script for stdio clients
- `MCP_CONFIG_PATH`: Path to a JSON configuration file

## Configuration File Format

JSON configuration file format:

```json
{
  "client_type": "http",
  "server_url": "http://localhost:8001/mcp",
  "server_script_path": "server.py"
}
```

## Development

To run the tests:

```bash
pytest tests/
```

## License

MIT 
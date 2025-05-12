#!/usr/bin/env python
# Load environment variables from .env file first, before any other imports
import os
from dotenv import load_dotenv

# Load .env file before any other imports
load_dotenv()
print(f"DATA_DIR from env: {os.environ.get('DATA_DIR', 'Not set')}")

import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
import json

# Add project root to Python path if needed
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
from fastapi import Request
from fastapi.openapi.utils import get_openapi
from starlette.responses import JSONResponse
from fastapi_mcp import FastApiMCP

# Import the app instance from app.py
from app import app

# Initialize these components first
from src.utils.logger import logger
from src.utils.filesystem import FileSystemManager
from src.utils.config import Config

# Import library content handler
from app_integration import register_library_content_endpoint

# Initialize API components
from src.api.init import initialize_api
initialize_api()

# Load configuration
config = Config.get_server_config()
dirs = Config.get_data_directories()

# Configure test environment if enabled
if config["tools_enabled"]:
    os.environ["ENABLE_TEST_TOOLS"] = "true"
    
# Set HERCULES_ROOT for compatibility with existing code
os.environ["HERCULES_ROOT"] = str(dirs["hercules_root"])

# Configure rotating log handler for file logs
FileSystemManager.ensure_dir(Path('src/api/logs'))
handler = RotatingFileHandler(
    'src/api/logs/server.log',
    maxBytes=10*1024*1024, 
    backupCount=5
)
handler.setFormatter(
    logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
)
root_logger = logging.getLogger()
root_logger.addHandler(handler)

# Custom logging handler to push log records to WebSocket clients
class WebSocketLogHandler(logging.Handler):
    def __init__(self, manager):
        super().__init__()
        self.manager = manager
        self.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        # Queue to store logs across threads
        import queue
        self.log_queue = queue.Queue()
        # Set the log level to capture all logs (DEBUG and above)
        self.setLevel(logging.DEBUG)

    def emit(self, record):
        try:
            log_entry = self.format(record)
            # Store in queue for asynchronous processing
            self.log_queue.put(log_entry)
            # Also print to console for immediate feedback with more visible marker
            print(f">>>>>>> LOG: {log_entry}")
        except Exception as e:
            print(f"Error in log handler: {e}")

# Import the WebSocket connection manager 
from src.api.websocket import manager as websocket_manager

# Register a task to process logs from the queue
def setup_log_processor(app, handler):
    @app.on_event("startup")
    async def start_log_processor():
        # Start background task to process logs
        asyncio.create_task(process_logs(handler))
        # Log something to verify the handler is working
        logger.info("Log processor started - WebSocket logging is active")

    async def process_logs(handler):
        while True:
            try:
                # Check if there are any logs to process
                if not handler.log_queue.empty():
                    # Process up to 10 logs at a time to avoid blocking
                    for _ in range(min(10, handler.log_queue.qsize())):
                        try:
                            log_entry = handler.log_queue.get_nowait()
                            await handler.manager.broadcast(log_entry)
                            handler.log_queue.task_done()
                            # Print again to verify broadcast attempt
                            print(f"BROADCAST: {log_entry}")
                        except handler.log_queue.Empty:
                            break
                        except Exception as e:
                            print(f"Error broadcasting log: {e}")
            except Exception as e:
                print(f"Error processing log queue: {e}")
            
            # Sleep to avoid high CPU usage
            await asyncio.sleep(0.1)

# Attach WebSocket log handler
ws_handler = WebSocketLogHandler(websocket_manager)
root_logger.addHandler(ws_handler)

# Now import router from routes - after app is defined
from src.api.routes import router

# Include API routes before MCP setup
app.include_router(router, prefix="")

# Register library content endpoints
register_library_content_endpoint(app)

# Now set up the MCP server after routes are included
mcp = FastApiMCP(app,
                 name="Hercules",

                 description="""
                 Description
TestFlow Orchestrator is an MCP server that bridges test discovery and execution through a streamlined API workflow. It enables users to run existing automated tests without managing complex infrastructure details.
Workflow Overview

Discovery: When users request a test run, system calls getAllContent to identify the requested test from the library of feature scripts and test data files
Execution: System then invokes runTestsFromTemplate to execute identified tests with appropriate templates and configurations
Results: Each execution receives a unique ID with dedicated storage for artifacts and results

The system handles all test resource management, configuration, and execution in a unified interface, requiring minimal user input to run complex test scenarios.
                 """,
                 # describe_all_responses=True,
                 # describe_full_response_schema=True,
                 # Explicitly include the run-from-template endpoint to ensure it's exposed
                 include_operations=["getTestChecking","getExecutionList","getExecutionDetails","runningATemplate"],
                 )
mcp.mount()

# Force refresh the MCP server to make sure all routes are detected
mcp.setup_server()

# Set up log processor to handle async logging
setup_log_processor(app, ws_handler)

# Function to periodically flush the database
async def flush_database_periodically():
    """Periodically flush the database to ensure all changes are written to disk."""
    from src.utils.database import db
    while True:
        try:
            db.flush()
            logger.debug("Periodic database flush completed")
        except Exception as e:
            logger.error(f"Error during periodic database flush: {e}")
        # Flush every 5 seconds
        await asyncio.sleep(5)

# Register the periodic flush task at startup
@app.on_event("startup")
async def start_db_flush_task():
    """Start the background task to periodically flush the database."""
    asyncio.create_task(flush_database_periodically())
    logger.info("Database flush task started")

# Custom OpenAPI schema
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    # Check if our custom YAML file exists
    yaml_path = Path(__file__).parent / "openapi.yaml"
    if yaml_path.exists():
        try:
            import yaml
            with open(yaml_path, 'r') as f:
                openapi_schema = yaml.safe_load(f)
            logger.info(f"Loaded custom OpenAPI schema from {yaml_path}")
            app.openapi_schema = openapi_schema
            return app.openapi_schema
        except Exception as e:
            logger.error(f"Error loading custom OpenAPI schema: {e}")
    
    # Fallback to default schema generation if YAML isn't available
    logger.info("Falling back to dynamically generated OpenAPI schema")
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add custom documentation
    openapi_schema["info"]["x-logo"] = {
        "url": "https://testzeus.io/logo.png"
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

# Run server when script is executed directly
if __name__ == "__main__":
    import uvicorn
    import socket
    
    # Load server configuration
    config = Config.get_server_config()
    host = config["host"]
    port = config["port"]
    reload = config["reload"]
    
    # Try to find an available port if the default one is in use
    max_port_attempts = 0
    original_port = port
    
    for attempt in range(max_port_attempts):
        try:
            # Test if port is available
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((host, port))
                # Port is available, break the loop
                break
        except OSError:
            logger.warning(f"Port {port} is already in use, trying {port + 1}...")
            port += 1
            
    if port != original_port:
        logger.info(f"Using alternative port {port} because original port {original_port} was in use")
    
    logger.info(f"Starting TestZeus Hercules API server on {host}:{port}")
    logger.info(f"API documentation available at http://localhost:{port}/api/docs")
    logger.info(f"MCP endpoint available at http://localhost:{port}/mcp")
    
    # Run the server
    try:
        uvicorn.run(
            "server:app",
            host=host,
            port=port,
            reload=reload
        )
    except OSError as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)

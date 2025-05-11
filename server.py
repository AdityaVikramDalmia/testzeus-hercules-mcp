#!/usr/bin/env python
import os
import sys
import logging
from pathlib import Path
from logging.handlers import RotatingFileHandler

# Add project root to Python path if needed
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

# Now import the modules after adjusting sys.path
from src.api.routes import router
from src.api.websocket import manager as websocket_manager
from src.api.init import initialize_api
from src.utils.logger import logger
from src.utils.filesystem import FileSystemManager
from src.utils.config import Config

# Initialize API components
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

# Create FastAPI app
app = FastAPI(
    title="TestZeus Hercules API",
    description="API for running TestZeus Hercules tests",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="")

# Set up log processor to handle async logging
setup_log_processor(app, ws_handler)

# Custom OpenAPI schema
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
        
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
    max_port_attempts = 10
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

# === server_http.py ===
#!/usr/bin/env python
# (This is your existing FastAPI + FastApiMCP HTTP server)
import os
from dotenv import load_dotenv
load_dotenv()

import sys, asyncio, socket, logging
from pathlib import Path
from logging.handlers import RotatingFileHandler
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi_mcp import FastApiMCP

# app definition and setup (your existing code)
from app import app  # assume app: FastAPI instance
from src.utils.logger import logger
from src.utils.filesystem import FileSystemManager
from src.utils.config import Config
from src.api.init import initialize_api
from app_integration import register_library_content_endpoint
from src.api.routes import router
from src.api.websocket import manager as websocket_manager

# initialize and include routes
initialize_api()
config = Config.get_server_config()
dirs = Config.get_data_directories()
if config["tools_enabled"]:
    os.environ["ENABLE_TEST_TOOLS"] = "true"
os.environ["HERCULES_ROOT"] = str(dirs["hercules_root"])
FileSystemManager.ensure_dir(Path('src/api/logs'))
handler = RotatingFileHandler('src/api/logs/server.log', maxBytes=10*1024*1024, backupCount=5)
handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
root_logger = logging.getLogger()
root_logger.addHandler(handler)

# WebSocket log handler omitted for brevity

app.include_router(router, prefix="")
register_library_content_endpoint(app)

# MCP HTTP mounting
mcp_http = FastApiMCP(
    app,
    name="Hercules",
    description="TestFlow Orchestrator ...",
    describe_all_responses=True,
    describe_full_response_schema=True,
    include_operations=["runTestsFromTemplate","getAllContent"],
)
mcp_http.mount()
mcp_http.setup_server()

# periodic flush task omitted

# custom OpenAPI omitted
app.openapi = lambda: get_openapi(title=app.title, version=app.version, description=app.description, routes=app.routes)

# Run via Uvicorn
if __name__ == "__main__":
    host, port, reload = config["host"], config["port"], config["reload"]
    # port detection omitted
    import uvicorn
    uvicorn.run("server_http:app", host=host, port=port, reload=reload)


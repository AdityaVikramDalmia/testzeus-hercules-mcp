#!/usr/bin/env python
"""
Standalone MCP server exposing getAllContent and runTestsFromTemplate over stdio.
"""
import os
from dotenv import load_dotenv
load_dotenv()
import asyncio

from fastmcp import FastMCP
# Import the core business logic for the tools
from src.api.routes import  run_tests_from_template

# Initialize API internals (same as HTTP server)
from src.api.init import initialize_api
initialize_api()

# Create the MCP server instance
description = """
TestFlow Orchestrator is an MCP server that bridges test discovery and execution through a streamlined API workflow.
Discovery: getAllContent\nExecution: runTestsFromTemplate\nResults: Unique IDs and artifact storage
"""
mcp = FastMCP(
    name="Hercules",
    instructions=description,
)

# Register tools
# @mcp.tool(name="getAllContent")
# async def getAllContent() -> dict:
#     """List all available test templates and metadata."""
#     return await get_all_content()

@mcp.tool(name="runTestsFromTemplate")
async def runTestsFromTemplate(template_id: str, params: dict) -> dict:
    """Execute the specified test template with given parameters."""
    return await run_tests_from_template(template_id, params)


# Entrypoint
if __name__ == "__main__":
    # Run MCP over stdio transport
    mcp.run()  # defaults to stdio

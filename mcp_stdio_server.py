#!/usr/bin/env python
"""
Minimal, barebones MCP server exposing test functionality over stdio.
"""
import os
import sys
import json
import asyncio
import traceback

# Add debug logging at the very start
print("Starting minimal MCP server script...")

try:
    # Check for required packages
    try:
        from dotenv import load_dotenv
        print("Successfully imported dotenv")
    except ImportError as e:
        print(f"ERROR: Missing dotenv package: {e}")
        print("Please install required packages: pip install python-dotenv")
        sys.exit(1)

    load_dotenv()

    try:
        from fastmcp import FastMCP
        print("Successfully imported FastMCP")
    except ImportError as e:
        print(f"ERROR: Failed to import FastMCP: {e}")
        print("Please install FastMCP: pip install fastmcp")
        sys.exit(1)

    # Import the core business logic for the tools
    try:
        from src.api.routes import run_tests_from_template
        print("Successfully imported run_tests_from_template")
    except ImportError as e:
        print(f"ERROR: Failed to import from src.api.routes: {e}")
        print("Current working directory:", os.getcwd())
        print("Python path:", sys.path)
        sys.exit(1)

    # Initialize API internals (same as HTTP server)
    try:
        from src.api.init import initialize_api
        print("Successfully imported initialize_api")
        initialize_api()
        print("API initialized successfully")
    except Exception as e:
        print(f"ERROR initializing API: {e}")
        traceback.print_exc()
        sys.exit(1)

    # Create a simple function for getAllContent
    async def get_all_content():
        """Basic implementation that returns empty lists"""
        print("get_all_content called")
        return {
            "test_data_list": [],
            "feature_data_list": []
        }

    # Create the MCP server instance
    print("Creating FastMCP instance...")
    mcp = FastMCP(
        name="Hercules",
        instructions="TestFlow Orchestrator is an MCP server that bridges test discovery and execution.",
    )

    # Register basic tools
    @mcp.tool(name="getAllContent")
    async def getAllContent() -> dict:
        """List all available test templates and metadata."""
        print("getAllContent tool called")
        return await get_all_content()

    @mcp.tool(name="runTestsFromTemplate")
    async def runTestsFromTemplate(test_infos: list, mock: bool = False) -> dict:
        """Execute the specified test template with given parameters."""
        print(f"runTestsFromTemplate called with {len(test_infos)} tests, mock={mock}")
        return await run_tests_from_template(test_infos, mock)

    # Entrypoint
    if __name__ == "__main__":
        try:
            print("Starting MCP server over stdio transport...")
            mcp.run()  # defaults to stdio
        except Exception as e:
            print(f"ERROR during MCP run: {e}")
            traceback.print_exc()
            sys.exit(1)

except Exception as e:
    print(f"FATAL ERROR: {e}")
    traceback.print_exc()
    sys.exit(1)

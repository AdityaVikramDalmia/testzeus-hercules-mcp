#!/usr/bin/env python
"""
Example MCP client communicating over stdio with mcp_stdio_server.py
"""
import asyncio
from fastmcp import Client
from fastmcp.client.transports import PythonStdioTransport

async def main():
    # Launch MCP server as subprocess via PythonStdioTransport
    transport = PythonStdioTransport(cmd=["python", "mcp_stdio_server.py"])
    async with Client(transport=transport) as client:
        tools = await client.list_tools()
        print("Available tools:", tools)

        # Example invocation of runTestsFromTemplate
        template = tools.get("runTestsFromTemplate")
        if template:
            response = await client.call_tool(
                "runTestsFromTemplate",
                {"template_id": "sample_template", "params": {}}
            )
            print("runTestsFromTemplate response:", response)

if __name__ == "__main__":
    asyncio.run(main())

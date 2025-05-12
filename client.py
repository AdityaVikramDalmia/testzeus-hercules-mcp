# client.py
import asyncio
from fastmcp import Client

async def main():
    # This will spawn 'server.py' as a child process and use stdio transport
    async with Client("server.py") as client:
        tools = await client.list_tools()
        print("Tools available:", tools)
        # Example: call the runTestsFromTemplate tool
        response = await client.call_tool(
            "runTestsFromTemplate",
            {"template_id": "TEMPLATE_NAME", "params": {"key": "value"}}
        )
        print("Result:", response.json())

if __name__ == "__main__":
    asyncio.run(main())

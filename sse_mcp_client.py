from typing import Optional, Dict, Any, List
import asyncio
import json
import os
import traceback
from datetime import datetime
import aiohttp
from aiohttp import ClientSession
from anthropic import Anthropic
from anthropic.types import Message
from src.utils.logger import logger


class SSEMCPClient:
    """SSE-based MCP client for connecting to server-sent events based MCP servers"""
    
    def __init__(self, server_url: str = None):
        """Initialize an SSE-based MCP client.
        
        Args:
            server_url: The URL of the MCP server. Defaults to http://localhost:8001/mcp.
        """
        self.server_url = server_url or "http://localhost:8001/mcp"
        self.session: Optional[ClientSession] = None
        self.llm = Anthropic()
        self.tools = []
        self.messages = []
        self.logger = logger

    async def connect(self):
        """Connect to the MCP server."""
        try:
            self.session = aiohttp.ClientSession()
            # Test the connection
            async with self.session.get(f"{self.server_url}/info") as response:
                if response.status != 200:
                    raise ConnectionError(f"Failed to connect to MCP server: {response.status}")
                info = await response.json()
                self.logger.info(f"Connected to SSE MCP server: {info.get('name', 'Unknown')}")
            
            # Fetch available tools
            await self.get_mcp_tools()
            return True
        except Exception as e:
            self.logger.error(f"Error connecting to MCP server: {e}")
            traceback.print_exc()
            if self.session:
                await self.session.close()
                self.session = None
            raise

    async def get_mcp_tools(self):
        """Get available tools from the MCP server."""
        try:
            if not self.session:
                raise ConnectionError("Not connected to MCP server")
            
            async with self.session.get(f"{self.server_url}/list-tools") as response:
                if response.status != 200:
                    raise ConnectionError(f"Failed to get tools: {response.status}")
                
                data = await response.json()
                tools = data.get("tools", [])
                
                self.tools = [
                    {
                        "name": tool.get("name"),
                        "description": tool.get("description"),
                        "input_schema": tool.get("inputSchema"),
                    }
                    for tool in tools
                ]
                
                self.logger.info(f"Available tools: {[tool['name'] for tool in self.tools]}")
                return self.tools
        except Exception as e:
            self.logger.error(f"Error getting MCP tools: {e}")
            raise

    async def call_tool(self, tool_name: str, tool_args: Dict[str, Any]):
        """Call a tool on the MCP server.
        
        Args:
            tool_name: The name of the tool to call
            tool_args: The arguments to pass to the tool
        
        Returns:
            The result of the tool call
        """
        try:
            if not self.session:
                raise ConnectionError("Not connected to MCP server")
            
            payload = {
                "name": tool_name,
                "arguments": tool_args
            }
            
            async with self.session.post(
                f"{self.server_url}/call-tool", 
                json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Tool call failed: {response.status} - {error_text}")
                
                result = await response.json()
                return result
        except Exception as e:
            self.logger.error(f"Error calling tool {tool_name}: {e}")
            raise

    async def process_query(self, query: str):
        """Process a user query through the LLM and handle tool calls.
        
        Args:
            query: The user's query
            
        Returns:
            The conversation history
        """
        try:
            self.logger.info(f"Processing query: {query}")
            user_message = {"role": "user", "content": query}
            self.messages = [user_message]

            while True:
                response = await self.call_llm()

                # The response is a text message
                if response.content[0].type == "text" and len(response.content) == 1:
                    assistant_message = {
                        "role": "assistant",
                        "content": response.content[0].text,
                    }
                    self.messages.append(assistant_message)
                    await self.log_conversation()
                    break

                # The response is a tool call
                assistant_message = {
                    "role": "assistant",
                    "content": response.to_dict()["content"],
                }
                self.messages.append(assistant_message)
                await self.log_conversation()

                for content in response.content:
                    if content.type == "tool_use":
                        tool_name = content.name
                        tool_args = content.input
                        tool_use_id = content.id
                        
                        self.logger.info(f"Calling tool {tool_name} with args {tool_args}")
                        
                        try:
                            result = await self.call_tool(tool_name, tool_args)
                            
                            self.logger.info(f"Tool {tool_name} result: {str(result)[:100]}...")
                            
                            self.messages.append({
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": tool_use_id,
                                        "content": result,
                                    }
                                ],
                            })
                            await self.log_conversation()
                        except Exception as e:
                            self.logger.error(f"Error calling tool {tool_name}: {e}")
                            self.messages.append({
                                "role": "user",
                                "content": [
                                    {
                                        "type": "tool_result",
                                        "tool_use_id": tool_use_id,
                                        "content": f"Error: {str(e)}",
                                    }
                                ],
                            })
                            await self.log_conversation()

            return self.messages
        except Exception as e:
            self.logger.error(f"Error processing query: {e}")
            raise

    async def call_llm(self):
        """Call the LLM with the current conversation history."""
        try:
            self.logger.info("Calling LLM")
            return self.llm.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=1000,
                messages=self.messages,
                tools=self.tools,
            )
        except Exception as e:
            self.logger.error(f"Error calling LLM: {e}")
            raise

    async def log_conversation(self):
        """Log the current conversation to a file."""
        os.makedirs("conversations", exist_ok=True)

        serializable_conversation = []

        for message in self.messages:
            try:
                serializable_message = {"role": message["role"], "content": []}

                # Handle both string and list content
                if isinstance(message["content"], str):
                    serializable_message["content"] = message["content"]
                elif isinstance(message["content"], list):
                    for content_item in message["content"]:
                        if hasattr(content_item, "to_dict"):
                            serializable_message["content"].append(content_item.to_dict())
                        elif hasattr(content_item, "dict"):
                            serializable_message["content"].append(content_item.dict())
                        elif hasattr(content_item, "model_dump"):
                            serializable_message["content"].append(content_item.model_dump())
                        else:
                            serializable_message["content"].append(content_item)

                serializable_conversation.append(serializable_message)
            except Exception as e:
                self.logger.error(f"Error processing message: {str(e)}")
                self.logger.debug(f"Message content: {message}")
                raise

        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = os.path.join("conversations", f"conversation_{timestamp}.json")

        try:
            with open(filepath, "w") as f:
                json.dump(serializable_conversation, f, indent=2, default=str)
        except Exception as e:
            self.logger.error(f"Error writing conversation to file: {str(e)}")
            self.logger.debug(f"Serializable conversation: {serializable_conversation}")
            raise

    async def cleanup(self):
        """Close the HTTP session."""
        try:
            if self.session:
                await self.session.close()
                self.session = None
            self.logger.info("Disconnected from MCP server")
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            traceback.print_exc()
            raise 
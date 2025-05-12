#!/usr/bin/env python
import asyncio
import argparse
import os
from mcp_client_factory import MCPClientFactory
from utils.logger import logger

async def run_client(client_type, server_url=None, server_script=None, query=None):
    """Run an MCP client with the given parameters.
    
    Args:
        client_type: Type of client to create ("http" or "stdio")
        server_url: URL of the HTTP MCP server (for HTTP clients)
        server_script: Path to the server script (for stdio clients)
        query: Query to send to the LLM
    """
    try:
        # Create client using the factory
        client = await MCPClientFactory.create_client(
            client_type=client_type,
            server_url=server_url,
            server_script_path=server_script
        )
        
        logger.info(f"Successfully created {client_type} client")
        
        # Process query
        if query:
            logger.info(f"Processing query: {query}")
            messages = await client.process_query(query)
            
            # Print the final response
            final_message = messages[-1]
            if final_message["role"] == "assistant":
                if isinstance(final_message["content"], str):
                    print("\nFinal response:")
                    print(final_message["content"])
                else:
                    print("\nFinal response (tool call):")
                    print(final_message["content"])
        
    except Exception as e:
        logger.error(f"Error running client: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Clean up
        if 'client' in locals():
            await client.cleanup()

async def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Advanced MCP Client Example")
    parser.add_argument("--client-type", choices=["http", "stdio"], default="http",
                      help="Type of MCP client to use (default: http)")
    parser.add_argument("--server-url", default=None,
                      help="MCP server URL for HTTP clients (default: http://localhost:8001/mcp)")
    parser.add_argument("--server-script", default=None,
                      help="Path to server script for stdio clients (e.g., server.py)")
    parser.add_argument("--config", default=None,
                      help="Path to client configuration file")
    parser.add_argument("--env", action="store_true",
                      help="Load configuration from environment variables")
    parser.add_argument("query", nargs="?", default="What tools are available?",
                      help="Query to send to the LLM")
    args = parser.parse_args()
    
    # Create client based on CLI arguments or environment
    if args.env:
        # Create client from environment variables
        logger.info("Creating client from environment variables")
        try:
            client = await MCPClientFactory.create_from_env()
            
            # Process query
            logger.info(f"Processing query: {args.query}")
            messages = await client.process_query(args.query)
            
            # Print the final response
            final_message = messages[-1]
            if final_message["role"] == "assistant":
                if isinstance(final_message["content"], str):
                    print("\nFinal response:")
                    print(final_message["content"])
                else:
                    print("\nFinal response (tool call):")
                    print(final_message["content"])
                    
            # Clean up
            await client.cleanup()
            
        except Exception as e:
            logger.error(f"Error using client from environment: {e}")
            import traceback
            traceback.print_exc()
    
    elif args.config:
        # Create client from config file
        logger.info(f"Creating client from config file: {args.config}")
        try:
            client = await MCPClientFactory.create_client(
                config_path=args.config
            )
            
            # Process query
            logger.info(f"Processing query: {args.query}")
            messages = await client.process_query(args.query)
            
            # Print the final response
            final_message = messages[-1]
            if final_message["role"] == "assistant":
                if isinstance(final_message["content"], str):
                    print("\nFinal response:")
                    print(final_message["content"])
                else:
                    print("\nFinal response (tool call):")
                    print(final_message["content"])
                    
            # Clean up
            await client.cleanup()
            
        except Exception as e:
            logger.error(f"Error using client from config: {e}")
            import traceback
            traceback.print_exc()
    
    else:
        # Create client based on command line arguments
        await run_client(
            client_type=args.client_type,
            server_url=args.server_url,
            server_script=args.server_script,
            query=args.query
        )

if __name__ == "__main__":
    asyncio.run(main()) 
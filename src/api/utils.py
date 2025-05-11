#!/usr/bin/env python
import os
import json
import re
import uuid
import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Tuple

from src.utils.logger import logger
from src.utils.filesystem import FileSystemManager

class APIUtils:
    """Utility functions specific to the API server."""
    
    # Class-level variable to hold a reference to the WebSocket manager
    # This avoids circular imports between modules
    _websocket_manager = None
    
    @classmethod
    def set_websocket_manager(cls, manager):
        """Set the WebSocket manager reference.
        
        Args:
            manager: WebSocket connection manager instance
        """
        cls._websocket_manager = manager
        
    @classmethod
    def broadcast_test_log(cls, log_message: str, execution_id: str):
        """Broadcast a log message to WebSocket clients for a specific execution ID.
        
        Args:
            log_message: The log message to broadcast
            execution_id: The execution ID
        """
        if cls._websocket_manager is not None:
            try:
                # Create async task to broadcast the message
                asyncio.create_task(cls._websocket_manager.broadcast_execution_log(log_message, execution_id))
            except Exception as e:
                logger.debug(f"Error broadcasting log: {e}")
    
    @staticmethod
    def generate_execution_id() -> str:
        """Generate a unique execution ID.
        
        Returns:
            str: Unique execution ID
        """
        return str(uuid.uuid4())
    
    @staticmethod
    def get_timestamp() -> str:
        """Get current timestamp in ISO format.
        
        Returns:
            str: Current timestamp
        """
        return datetime.now().isoformat()
    
    @staticmethod
    def format_run_timestamp() -> str:
        """Get current timestamp formatted for run directories.
        
        Returns:
            str: Formatted timestamp for run directories
        """
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    @staticmethod
    def update_file_paths(file_path: Path, old_base_path: str, new_base_path: str) -> None:
        """Update file paths in result files during archiving.
        
        Args:
            file_path: Path to the file to update
            old_base_path: Original base path to replace
            new_base_path: New base path
        """
        if not file_path.exists() or not file_path.is_file():
            return
            
        try:
            with open(file_path, 'r') as f:
                content = f.read()
                
            # Replace paths in content
            updated_content = content.replace(old_base_path, new_base_path)
            
            with open(file_path, 'w') as f:
                f.write(updated_content)
        except Exception as e:
            logger.error(f"Error updating paths in {file_path}: {e}")
    
    @staticmethod
    async def run_command(cmd: List[str], cwd: Optional[Path] = None, timeout: int = 600, env: Optional[Dict[str, str]] = None, log_prefix: str = "[PROCESS]") -> Tuple[int, str, str]:
        """Run a shell command asynchronously and stream output to logger.
        
        Args:
            cmd: Command and arguments as a list
            cwd: Current working directory
            timeout: Command timeout in seconds
            env: Environment variables to pass to the subprocess
            log_prefix: Prefix for log messages from the subprocess
            
        Returns:
            Tuple containing (return_code, stdout, stderr)
        """
        # Log command execution with sanitized command (hide any sensitive info)
        safe_cmd = []
        for arg in cmd:
            if any(sensitive in arg.lower() for sensitive in ["key", "password", "secret", "token"]):
                safe_cmd.append("[REDACTED]")
            else:
                safe_cmd.append(arg)
        
        logger.info(f"Executing command: {' '.join(safe_cmd)}")
        
        # Log if using custom environment
        if env:
            logger.info(f"Using custom environment with {len(env)} variables")
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(cwd) if cwd else None,
                env=env
            )
            
            # Collect full output for the return value
            full_stdout = []
            full_stderr = []
            
            # Read and stream stdout and stderr line by line as they are produced
            async def stream_output():
                try:
                    # Stream stdout
                    while True:
                        line = await process.stdout.readline()
                        if not line:
                            break
                        line_str = line.decode('utf-8').rstrip()
                        full_stdout.append(line_str)
                        log_message = f"{log_prefix} {line_str}"
                        logger.info(log_message)
                        
                        # Extract execution ID from log prefix if present
                        # Format is [EXEC:execution_id][...][...]
                        from src.api.websocket import manager
                        if log_prefix.startswith("[EXEC:"):
                            try:
                                exec_id = log_prefix.split("]")[0].replace("[EXEC:", "")
                                asyncio.create_task(manager.broadcast_execution_log(log_message, exec_id))
                            except Exception as e:
                                logger.debug(f"Error broadcasting log: {e}")
                    
                    # Stream stderr
                    while True:
                        line = await process.stderr.readline()
                        if not line:
                            break
                        line_str = line.decode('utf-8').rstrip()
                        full_stderr.append(line_str)
                        log_message = f"{log_prefix} {line_str}"
                        logger.error(log_message)
                        
                        # Extract execution ID from log prefix if present
                        # Format is [EXEC:execution_id][...][...]
                        from src.api.websocket import manager
                        if log_prefix.startswith("[EXEC:"):
                            try:
                                exec_id = log_prefix.split("]")[0].replace("[EXEC:", "")
                                asyncio.create_task(manager.broadcast_execution_log(log_message, exec_id))
                            except Exception as e:
                                logger.debug(f"Error broadcasting log: {e}")
                except Exception as e:
                    logger.error(f"Error streaming process output: {e}")
                    # Continue with execution even if streaming fails
            
            # Start streaming in the background
            stream_task = asyncio.create_task(stream_output())
            
            # Wait for process to complete or timeout
            try:
                return_code = await asyncio.wait_for(process.wait(), timeout=timeout)
                # Wait for streaming to complete
                await stream_task
                return return_code, '\n'.join(full_stdout), '\n'.join(full_stderr)
            except asyncio.TimeoutError:
                # Cancel streaming task
                stream_task.cancel()
                process.kill()
                logger.error(f"{log_prefix} Command timed out after {timeout} seconds")
                return -1, '\n'.join(full_stdout), f"Command timed out after {timeout} seconds"
            except Exception as e:
                # Handle any other exceptions
                stream_task.cancel()
                process.kill()
                logger.error(f"{log_prefix} Command execution error: {e}")
                return -1, '\n'.join(full_stdout), f"Command execution error: {str(e)}"
                
        except Exception as e:
            logger.error(f"Error executing command {' '.join(cmd)}: {e}")
            return -1, "", str(e)
    
    @staticmethod
    def search_content(directory: Path, query: str) -> List[Dict[str, Any]]:
        """Search for content within files.
        
        Args:
            directory: Directory to search in
            query: Search query
            
        Returns:
            List of dictionaries with search results
        """
        results = []
        
        if not directory.exists() or not directory.is_dir():
            return results
            
        try:
            # Only search in feature files
            for file_path in directory.glob("**/*.feature"):
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                    
                    if query.lower() in content.lower():
                        # Find lines containing the query
                        lines = content.split('\n')
                        matching_lines = []
                        
                        for i, line in enumerate(lines):
                            if query.lower() in line.lower():
                                line_info = {
                                    "line_number": i + 1,
                                    "content": line.strip()
                                }
                                matching_lines.append(line_info)
                        
                        if matching_lines:
                            results.append({
                                "file": str(file_path),
                                "name": file_path.name,
                                "matching_lines": matching_lines
                            })
                except Exception as e:
                    logger.warning(f"Error reading file {file_path}: {e}")
                    
        except Exception as e:
            logger.error(f"Error searching in directory {directory}: {e}")
            
        return results

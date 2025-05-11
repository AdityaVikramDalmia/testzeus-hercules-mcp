#!/usr/bin/env python
import json
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from fastapi import WebSocket, WebSocketDisconnect

from src.utils.logger import logger

# Enhanced WebSocket connection manager with execution ID filtering
class ConnectionManager:
    def __init__(self):
        # Store connections with their execution ID subscriptions
        # Format: {websocket: {"execution_ids": [id1, id2, ...], "all_logs": True/False}}
        self.connections = {}

    async def connect(self, websocket: WebSocket, execution_id: Optional[str] = None, all_logs: bool = False):
        await websocket.accept()
        
        # Initialize connection with subscription info
        if websocket not in self.connections:
            self.connections[websocket] = {
                "execution_ids": [],
                "all_logs": all_logs
            }
        
        # Add execution ID subscription if provided
        if execution_id:
            self.connections[websocket]["execution_ids"].append(execution_id)
            logger.info(f"WebSocket connection subscribed to execution ID: {execution_id}")
        elif all_logs:
            self.connections[websocket]["all_logs"] = True
            logger.info(f"WebSocket connection subscribed to all logs")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.connections:
            del self.connections[websocket]

    async def broadcast(self, message: str, execution_id: Optional[str] = None):
        # Make a copy of connections to avoid modification during iteration
        connections = dict(self.connections)
        
        for websocket, subscriptions in connections.items():
            try:
                # Send message if the connection is subscribed to this execution ID
                # or if it's subscribed to all logs
                if (execution_id is None or 
                    execution_id in subscriptions["execution_ids"] or 
                    subscriptions["all_logs"]):
                    await websocket.send_text(message)
            except WebSocketDisconnect:
                # WebSocket was disconnected
                self.disconnect(websocket)
            except Exception as e:
                # Handle other exceptions
                logger.error(f"Error broadcasting message: {e}")
                try:
                    self.disconnect(websocket)
                except Exception:
                    # Connection might have been removed already
                    pass
                
    async def broadcast_execution_log(self, log_message: str, execution_id: str):
        """Broadcast a log message to clients subscribed to a specific execution ID.
        
        Args:
            log_message: The log message to broadcast
            execution_id: The execution ID the log is associated with
        """
        # Create a structured log message
        message = json.dumps({
            "type": "log",
            "execution_id": execution_id,
            "timestamp": datetime.now().isoformat(),
            "message": log_message
        })
        
        await self.broadcast(message, execution_id)

# Global instance that will be imported by other modules
manager = ConnectionManager()

#!/usr/bin/env python
"""Initialization module for API components.

This module sets up connections between various components to avoid circular imports.
"""

from src.api.websocket import manager as websocket_manager
from src.api.utils import APIUtils

def initialize_api():
    """Initialize API components and connect dependencies."""
    # Set the WebSocket manager in APIUtils
    APIUtils.set_websocket_manager(websocket_manager)

#!/usr/bin/env python
import os
import uuid
from pathlib import Path
from typing import Optional, Dict, Any

def get_data_dir() -> Path:
    """
    Get the data directory path from environment variable or default location.
    
    Returns:
        Path: The data directory path as a Path object
        
    Environment Variables:
        DATA_DIR: If set, this path will be used instead of the default location
    """
    # Check if DATA_DIR environment variable is set
    env_data_dir = os.environ.get("DATA_DIR")
    
    if env_data_dir:
        # Use the environment variable if it's set
        data_dir = Path(env_data_dir)
    else:
        # Default to project root /data directory
        # Get the project root directory (3 levels up from this file)
        project_root = Path(__file__).parent.parent.parent
        data_dir = project_root / "data"
    
    # Ensure the directory exists
    data_dir.mkdir(exist_ok=True)
    
    return data_dir


def get_root_dir() -> Path:
    """
    Get the data directory path from environment variable or default location.

    Returns:
        Path: The data directory path as a Path object

    Environment Variables:
        DATA_DIR: If set, this path will be used instead of the default location
    """
    # Check if DATA_DIR environment variable is set
    env_data_dir = os.environ.get("DATA_DIR")

    if env_data_dir:
        # Use the environment variable if it's set
        data_dir = Path(env_data_dir)
    else:
        # Default to project root /data directory
        # Get the project root directory (3 levels up from this file)
        project_root = Path(__file__).parent.parent.parent
        data_dir = project_root

    # Ensure the directory exists
    # data_dir.mkdir(exist_ok=True)

    return data_dir

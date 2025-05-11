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
    Get the root directory path of the project.

    Returns:
        Path: The project root directory path as a Path object

    Environment Variables:
        DATA_DIR: If set, this function will derive the root directory from it
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


def get_env_file_path() -> Path:
    """
    Get the path to the environment (.env) file based on environment variable or default location.
    
    Returns:
        Path: The path to the .env file
        
    Environment Variables:
        ENV_FILE_PATH: If set, this path will be used instead of the default location
    """
    # Check if ENV_FILE_PATH environment variable is set
    env_file_path = os.environ.get("ENV_FILE_PATH")
    
    if env_file_path:
        # Use the environment variable if it's set
        return Path(env_file_path)
    else:
        # Default to project root /.env file
        return get_root_dir() / ".env"

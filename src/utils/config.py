#!/usr/bin/env python
"""
Configuration module for TestZeus Hercules MCP.

This module centralizes all configuration settings and provides
accessor functions to retrieve configuration values with proper defaults.
"""
import os
from pathlib import Path
from typing import Dict, Any, Optional

from src.utils.paths import get_data_dir, get_root_dir
from src.utils.filesystem import FileSystemManager

class Config:
    """Configuration manager for TestZeus Hercules MCP."""
    
    @staticmethod
    def get_data_directories() -> Dict[str, Path]:
        """Get all data directories used by the application.
        
        Returns:
            Dict mapping directory names to Path objects
        """
        data_dir = get_data_dir()
        hercules_root = data_dir / "manager" / "exec"
        project_root_dir = get_root_dir()
        directories = {
            "project_root": project_root_dir,
            "data_dir": data_dir,
            "hercules_root": hercules_root,
            "perm_storage": data_dir / "manager" / "perm" / "ExecutionResultHistory",
            "library": data_dir / "manager" / "lib" / "features",
            "test_data_library": data_dir / "manager" / "lib" / "test_data",
            "opt_dir": hercules_root / "opt",
            "input_dir": hercules_root / "opt" / "input",
            "output_dir": hercules_root / "opt" / "output",
            "log_dir": hercules_root / "opt" / "log_files",
            "test_data_dir": hercules_root / "opt" / "test_data",
            "proofs_dir": hercules_root / "opt" / "proofs"
        }
        
        # Ensure critical directories exist
        for name in ["perm_storage", "library", "test_data_library", "input_dir", "output_dir"]:
            FileSystemManager.ensure_dir(directories[name])
            
        return directories
    
    @staticmethod
    def get_server_config() -> Dict[str, Any]:
        """Get server configuration from environment variables.
        
        Returns:
            Dict with server configuration
        """
        return {
            "host": os.getenv("API_HOST", "0.0.0.0"),
            "port": int(os.getenv("API_PORT", "8000")),
            "reload": os.getenv("API_RELOAD", "false").lower() == "true",
            "debug": os.getenv("SERVER_DEBUG", "false").lower() == "true",
            "tools_enabled": os.getenv("ENABLE_TEST_TOOLS", "true").lower() == "true"
        }
    
    @staticmethod
    def get_test_execution_config() -> Dict[str, Any]:
        """Get test execution configuration.
        
        Returns:
            Dict with test execution configuration
        """
        return {
            "default_timeout": 600,
            "max_archives_per_test": 10,
            "cleanup_threshold": 5  # Keep only this many directories per test
        }

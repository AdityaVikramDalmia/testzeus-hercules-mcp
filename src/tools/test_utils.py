#!/usr/bin/env python
"""
Test utilities for TestZeus Hercules.

This module provides helper functions for test execution and result processing.
"""
import json
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple, Union

from src.utils.logger import logger
from src.utils.config import Config
from src.utils.filesystem import FileSystemManager


class TestUtils:
    """Utilities for test execution and result processing."""
    
    @staticmethod
    def prepare_test_environment(test_id: str) -> Tuple[Dict[str, Path], bool]:
        """Prepare the test environment for execution.
        
        Args:
            test_id: Test ID or path
            
        Returns:
            Tuple of (paths dictionary, is_ready boolean)
        """
        # Normalize test ID
        if not test_id.endswith(".feature"):
            test_id += ".feature"
            
        # Get directories
        dirs = Config.get_data_directories()
        
        # Verify test file exists
        test_file = dirs["input_dir"] / test_id
        if not test_file.exists():
            logger.error(f"Test file not found: {test_file}")
            return dirs, False
            
        # Ensure output directories exist
        FileSystemManager.ensure_dir(dirs["output_dir"])
        FileSystemManager.ensure_dir(dirs["test_data_dir"])
        
        return dirs, True
    
    @staticmethod
    def process_test_result(result_file: Path) -> Dict[str, Any]:
        """Process test result file and extract summary.
        
        Args:
            result_file: Path to result JSON file
            
        Returns:
            Dict with result summary
        """
        if not result_file.exists():
            return {
                "status": "error",
                "error": "Result file not found"
            }
            
        try:
            with open(result_file, 'r') as f:
                result_data = json.load(f)
                
            # Extract summary
            summary = {
                "status": result_data.get("status", "unknown"),
                "passed_steps": result_data.get("passed_steps", 0),
                "failed_steps": result_data.get("failed_steps", 0),
                "total_steps": result_data.get("total_steps", 0),
                "duration": result_data.get("duration", 0),
                "result_file": str(result_file)
            }
            
            return summary
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in result file: {result_file}")
            return {
                "status": "error",
                "error": "Invalid JSON in result file"
            }
        except Exception as e:
            logger.error(f"Error processing result file: {e}")
            return {
                "status": "error",
                "error": f"Error processing result: {str(e)}"
            }
    
    @staticmethod
    def find_test_artifacts(test_id: str) -> Dict[str, List[str]]:
        """Find artifacts (proofs, logs) related to a test.
        
        Args:
            test_id: Test ID or path
            
        Returns:
            Dict with lists of artifact paths
        """
        # Normalize test ID and get test name
        if not test_id.endswith(".feature"):
            test_id += ".feature"
            
        test_name = Path(test_id).stem
        dirs = Config.get_data_directories()
        
        artifacts = {
            "proofs": [],
            "logs": [],
            "screenshots": []
        }
        
        # Find proof directories
        if dirs["proofs_dir"].exists():
            for item in dirs["proofs_dir"].iterdir():
                if item.is_dir() and item.name.startswith(test_name):
                    artifacts["proofs"].append(str(item))
                    
                    # Look for screenshots
                    screenshots_dir = item / "screenshots"
                    if screenshots_dir.exists():
                        for img in screenshots_dir.iterdir():
                            if img.suffix.lower() in [".png", ".jpg", ".jpeg"]:
                                artifacts["screenshots"].append(str(img))
        
        # Find log directories
        if dirs["log_dir"].exists():
            for item in dirs["log_dir"].iterdir():
                if item.is_dir() and item.name.startswith(test_name):
                    artifacts["logs"].append(str(item))
                    
        return artifacts

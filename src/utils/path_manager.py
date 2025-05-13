#!/usr/bin/env python
import os
import uuid
from pathlib import Path
from typing import Dict, Any, Optional

from src.utils.paths import get_data_dir, get_root_dir

class PathManager:
    """Manages dynamic execution paths for parallel test execution.
    
    This class creates and manages unique execution directory paths for each test run,
    allowing for parallel test execution without path conflicts.
    
    Example usage:
        path_manager = PathManager.create_for_execution(execution_id)
        input_dir = path_manager.get_input_dir()
        output_dir = path_manager.get_output_dir()
    """
    
    def __init__(self, execution_id: str = None, test_id: str = None):
        """Initialize a PathManager with optional execution and test IDs.
        
        Args:
            execution_id: Unique ID for this execution run
            test_id: Optional test ID for test-specific paths
        """
        self.data_dir = get_data_dir()
        self.project_root = get_root_dir()
        self.execution_id = execution_id or str(uuid.uuid4())
        self.test_id = test_id
        
        # Base execution directory
        self.hercules_root = self.data_dir / "manager" / "exec"
        
        # Dynamic execution path with unique ID
        self.exec_root = self.hercules_root / f"run_{self.execution_id}"
        self.opt_dir = self.exec_root / "opt"
        
        # Test-specific paths if test_id is provided
        if test_id:
            self.test_dir = self.opt_dir / "tests" / test_id
        else:
            self.test_dir = None
        
    @classmethod
    def create_for_execution(cls, execution_id: str = None) -> 'PathManager':
        """Create a new PathManager for an execution run.
        
        Args:
            execution_id: Optional execution ID, will generate a UUID if not provided
        
        Returns:
            A new PathManager instance configured for this execution
        """
        return cls(execution_id=execution_id)
    
    def create_for_test(self, test_id: str) -> 'PathManager':
        """Create a new PathManager for a specific test within this execution.
        
        Args:
            test_id: The test ID
        
        Returns:
            A new PathManager instance configured for this test
        """
        return PathManager(execution_id=self.execution_id, test_id=test_id)
    
    def ensure_directories(self):
        """Create all necessary directories for this execution/test."""
        from src.utils.filesystem import FileSystemManager
        
        # Create base execution directory
        FileSystemManager.ensure_dir(self.exec_root)
        FileSystemManager.ensure_dir(self.opt_dir)
        
        if self.test_dir:
            # Create test-specific directories
            FileSystemManager.ensure_dir(self.test_dir)
            FileSystemManager.ensure_dir(self.get_input_dir())
            FileSystemManager.ensure_dir(self.get_output_dir())
            FileSystemManager.ensure_dir(self.get_test_data_dir())
            FileSystemManager.ensure_dir(self.get_logs_dir())
            FileSystemManager.ensure_dir(self.get_proofs_dir())
        else:
            # Create general directories
            FileSystemManager.ensure_dir(self.get_tests_dir())
            FileSystemManager.ensure_dir(self.get_input_dir())
            FileSystemManager.ensure_dir(self.get_output_dir())
            FileSystemManager.ensure_dir(self.get_test_data_dir())
            FileSystemManager.ensure_dir(self.get_logs_dir())
            FileSystemManager.ensure_dir(self.get_proofs_dir())
    
    def get_all_paths(self) -> Dict[str, Path]:
        """Get all relevant paths as a dictionary.
        
        Returns:
            Dictionary mapping path names to Path objects
        """
        return {
            "execution_root": self.exec_root,
            "opt_dir": self.opt_dir,
            "tests_dir": self.get_tests_dir(),
            "input_dir": self.get_input_dir(),
            "output_dir": self.get_output_dir(),
            "test_data_dir": self.get_test_data_dir(),
            "logs_dir": self.get_logs_dir(),
            "proofs_dir": self.get_proofs_dir()
        }
    
    def get_tests_dir(self) -> Path:
        """Get the tests directory path."""
        return self.opt_dir / "tests"
    
    def get_input_dir(self) -> Path:
        """Get the input directory path."""
        if self.test_dir:
            return self.test_dir / "input"
        return self.opt_dir / "input"
    
    def get_output_dir(self) -> Path:
        """Get the output directory path."""
        if self.test_dir:
            return self.test_dir / "output"
        return self.opt_dir / "output"
    
    def get_test_data_dir(self) -> Path:
        """Get the test data directory path."""
        if self.test_dir:
            return self.test_dir / "test_data"
        return self.opt_dir / "test_data"
    
    def get_logs_dir(self) -> Path:
        """Get the logs directory path."""
        if self.test_dir:
            return self.test_dir / "log_files"
        return self.opt_dir / "log_files"
    
    def get_proofs_dir(self) -> Path:
        """Get the proofs directory path."""
        if self.test_dir:
            return self.test_dir / "proofs"
        return self.opt_dir / "proofs"
    
    def get_gherkin_files_dir(self) -> Path:
        """Get the gherkin files directory path."""
        return self.opt_dir / "gherkin_files"
    
    def get_library_root(self) -> Path:
        """Get the library root path."""
        return self.data_dir / "manager" / "long_term_lib" / "features"
    
    def get_test_data_library_root(self) -> Path:
        """Get the test data library root path."""
        return self.data_dir / "manager" / "long_term_lib" / "test_data"
    
    def get_perm_storage_root(self) -> Path:
        """Get the permanent storage root path."""
        return self.data_dir / "manager" / "perm" / "ExecutionResultHistory"

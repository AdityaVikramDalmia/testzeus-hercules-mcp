#!/usr/bin/env python
from pathlib import Path
import shutil
import os
from typing import Dict, Any, List, Union, Optional
from fastapi import HTTPException

class FileSystemManager:
    """Utility class for filesystem operations with improved safety and consistency."""
    
    @staticmethod
    def safe_path_join(base_path: Union[str, Path], *paths: str, must_exist: bool = False) -> Path:
        """Join paths safely and ensure the result is within the base path.
        
        Args:
            base_path: The root path that should contain the result
            paths: Path components to join
            must_exist: If True, verify the path exists
            
        Returns:
            Path: The joined path object
            
        Raises:
            HTTPException: If the resulting path is outside the base_path or doesn't exist when must_exist=True
        """
        base = Path(base_path).resolve()
        
        # Use normpath to handle '..' components safely
        norm_path = os.path.normpath(os.path.join(*paths))
        result = (base / norm_path).resolve()
        
        # Security check: ensure result is within base directory
        if not str(result).startswith(str(base)):
            raise HTTPException(status_code=403, detail="Access denied: path outside of allowed directory")
        
        # Existence check if required
        if must_exist and not result.exists():
            raise HTTPException(status_code=404, detail=f"Path '{result.relative_to(base)}' not found")
            
        return result
    
    @staticmethod
    def safe_copy(src: Path, dst: Path) -> None:
        """Safely copy a file or directory to destination.
        
        Args:
            src: Source path
            dst: Destination path
        """
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        else:
            if dst.exists() and dst.is_dir():
                shutil.rmtree(dst)
            shutil.copy2(src, dst)
    
    @staticmethod
    def ensure_dir(path: Union[str, Path]) -> Path:
        """Ensure a directory exists.
        
        Args:
            path: Directory path
            
        Returns:
            Path: The directory path
        """
        path_obj = Path(path)
        path_obj.mkdir(parents=True, exist_ok=True)
        return path_obj
    
    @staticmethod
    def get_file_info(path: Path) -> Dict[str, Any]:
        """Get file information for API response.
        
        Args:
            path: Path to file or directory
            
        Returns:
            Dict with file information
        """
        name = path.name
        if path.is_dir():
            return {
                "name": name,
                "type": "directory",
                "path": str(path)
            }
        else:
            return {
                "name": name,
                "type": "file" if not name.endswith(".feature") else "feature",
                "path": str(path)
            }
    
    @staticmethod
    def list_files(directory: Path, pattern: Optional[str] = None) -> List[Dict[str, Any]]:
        """List files in a directory with optional pattern filtering.
        
        Args:
            directory: Directory to list files from
            pattern: Optional glob pattern to filter files
            
        Returns:
            List of file information dictionaries
        """
        if not directory.exists() or not directory.is_dir():
            return []
        
        files = []
        if pattern:
            items = list(directory.glob(pattern))
        else:
            items = list(directory.iterdir())
        
        for item in items:
            files.append(FileSystemManager.get_file_info(item))
        
        return files
    
    @staticmethod
    def search_files(directory: Path, query: str, case_sensitive: bool = False) -> List[Dict[str, Any]]:
        """Search for files containing query string in their name.
        
        Args:
            directory: Directory to search in
            query: Search query
            case_sensitive: Whether search should be case sensitive
            
        Returns:
            List of matching file information dictionaries
        """
        if not directory.exists() or not directory.is_dir():
            return []
        
        results = []
        for item in directory.rglob("*"):
            name = item.name
            if not case_sensitive:
                if query.lower() in name.lower():
                    results.append(FileSystemManager.get_file_info(item))
            else:
                if query in name:
                    results.append(FileSystemManager.get_file_info(item))
        
        return results

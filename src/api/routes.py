#!/usr/bin/env python
import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Union
import asyncio

from fastapi import APIRouter, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from src.api.models import TestRequest, TestInfosRequest, TestResponse, TestResult
from src.api.utils import APIUtils
from src.utils.filesystem import FileSystemManager
from src.utils.logger import logger
from src.utils.config import Config
from src.utils.path_manager import PathManager
from src.tools.test_tools import TestTools
from src.tools.test_utils import TestUtils

# Create router
router = APIRouter()

# Get configuration and directory paths
dirs = Config.get_data_directories()
exec_config = Config.get_test_execution_config()

# Reference commonly used directories
HERCULES_ROOT = dirs["hercules_root"]
PROJECT_ROOT_DIR = dirs["project_root"]
PERM_STORAGE_ROOT = dirs["perm_storage"]
LIBRARY_ROOT = dirs["library"]
TEST_DATA_LIBRARY_ROOT = dirs["test_data_library"]
INPUT_DIR = dirs["input_dir"]
OUTPUT_DIR = dirs["output_dir"]
OPT_DIR = dirs["opt_dir"]
LOG_DIR = dirs["log_dir"]
TEST_DATA_DIR = dirs["test_data_dir"]

# Test tracking
test_executions = {}

# Import the WebSocket connection manager from the dedicated module
from src.api.websocket import manager as websocket_manager


# Function to archive test results
async def archive_test_results(execution_id: str, test_id: str, run_dir: Union[str, Path]) -> Path:
    """Archive test results from the run directory to permanent storage.
    
    Args:
        execution_id: The unique execution ID
        test_id: The test ID (usually a feature filename)
        run_dir: The source directory containing test results
        
    Returns:
        Path: The archive directory path
    """
    run_dir_path = Path(run_dir)
    if not run_dir_path.exists():
        logger.warning(f"Run directory {run_dir_path} does not exist, nothing to archive")
        return None
        
    # Create archive directory
    archive_dir = PERM_STORAGE_ROOT / execution_id
    FileSystemManager.ensure_dir(archive_dir)
    
    try:
        # Copy run directory contents to archive
        FileSystemManager.safe_copy(run_dir_path, archive_dir)
        
        # Update file paths in JSON result files
        for json_file in archive_dir.glob("**/*.json"):
            APIUtils.update_file_paths(json_file, str(run_dir_path), str(archive_dir))
            
        logger.info(f"Archived test results for {test_id} to {archive_dir}")
        return archive_dir
        
    except Exception as e:
        logger.error(f"Error archiving test results: {e}")
        return None

# Function to clean up temporary execution directory
async def cleanup_exec():
    """Clean up all execution directories by completely wiping the opt directory."""
    
    try:
        # Get the opt directory path
        opt_path = dirs["opt_dir"]
        
        # Log the operation
        logger.info(f"Completely wiping opt directory: {opt_path}")
        
        # Check if directory exists and remove it
        if opt_path.exists():
            shutil.rmtree(opt_path)
        
        # Recreate basic directory structure
        os.makedirs(opt_path, exist_ok=True)
        os.makedirs(opt_path / "input", exist_ok=True)
        os.makedirs(opt_path / "output", exist_ok=True)
        os.makedirs(opt_path / "log_files", exist_ok=True)
        os.makedirs(opt_path / "test_data", exist_ok=True)
        os.makedirs(opt_path / "proofs", exist_ok=True)
        os.makedirs(opt_path / "gherkin_files", exist_ok=True)
        
        # Return success message
        return {
            "message": "Opt directory completely wiped and recreated",
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Error cleaning up execution directories: {e}")
        raise HTTPException(status_code=500, detail=f"Error during cleanup: {str(e)}")

# Background task for running tests
async def run_test_task(execution_id: str, test_id: str, options: Optional[Dict[str, Any]] = None):
    """Execute a test as a background task.
    
    Args:
        execution_id: Unique execution ID
        test_id: Test ID
        options: Test execution options including path_manager_id and directory paths
    """
    try:
        # Initialize options if None
        if options is None:
            options = {}
        
        # Get or recreate the PathManager
        path_manager_id = options.get("path_manager_id")
        
        if path_manager_id and path_manager_id in test_executions:
            # If the execution record has the PathManager stored, use it
            if "path_manager" in test_executions[path_manager_id]:
                path_manager = test_executions[path_manager_id]["path_manager"]
                logger.info(f"Using existing PathManager from execution {path_manager_id}")
            else:
                # Recreate PathManager for this execution/test
                path_manager = PathManager.create_for_execution(path_manager_id)
                test_path_manager = path_manager.create_for_test(test_id)
                logger.info(f"Recreated PathManager for execution {path_manager_id} and test {test_id}")
        else:
            # Create a new PathManager if none exists
            path_manager = PathManager.create_for_execution(execution_id)
            test_path_manager = path_manager.create_for_test(test_id)
            logger.info(f"Created new PathManager for execution {execution_id} and test {test_id}")
        
        start_time = datetime.now().isoformat()
        test_executions[execution_id] = {
            "test_id": test_id,
            "status": "running",
            "start_time": start_time,
            "path_manager_id": path_manager_id or execution_id
        }
        
        # Get the directory paths from options
        test_dir = Path(options.get("test_dir"))
        test_input_dir = Path(options.get("input_dir"))
        test_output_dir = Path(options.get("output_dir"))
        test_data_dir = Path(options.get("test_data_dir"))
        
        # Add directories to the test execution record
        test_executions[execution_id]["test_dir"] = str(test_dir)
        
        logger.info(f"Using dynamic directories for test {test_id}:")
        logger.info(f"  - Test dir: {test_dir}")
        logger.info(f"  - Input dir: {test_input_dir}")
        logger.info(f"  - Output dir: {test_output_dir}")
        logger.info(f"  - Test data dir: {test_data_dir}")
        
        # Run the test
        env_file = str(PROJECT_ROOT_DIR / ".env")
        
        # Add execution metadata for logging purposes
        metadata = {
            "execution_id": execution_id,
            "start_time": start_time,
            "headless": options.get("headless", False),
            "browser": options.get("browser", "chromium"),
            "path_manager_id": path_manager_id or execution_id,
            "test_id": test_id
        }
        
        # Prepare options for test execution
        test_options = options.copy()
        
        # Ensure TestTools can find the files in the correct directories
        test_options["input_dir"] = str(test_input_dir)
        test_options["output_dir"] = str(test_output_dir)
        test_options["test_data_dir"] = str(test_data_dir)
        
        # Execute the test
        logger.info(f"Executing test {test_id} using dynamic paths...")
        result = await TestTools.run_test(test_id, test_options, env_file, metadata=metadata)
        
        # Process the result
        try:
            result_data = json.loads(result)
            status = result_data.get("status", "completed")
        except json.JSONDecodeError:
            # If result is not valid JSON, it's likely an error message
            status = "failed"
            result_data = {"error": result}
        
        # Generate a timestamp for this run
        run_timestamp = APIUtils.format_run_timestamp()
        
        # Results are in the dynamic test directory
        run_dir = test_output_dir / f"run_{run_timestamp}"
        archive_path = test_dir
            
        # Update test execution status
        end_time = datetime.now().isoformat()
        test_executions[execution_id] = {
            "test_id": test_id,
            "status": status,
            "start_time": start_time,
            "end_time": end_time,
            "result": result_data,
            "archived_path": str(archive_path) if archive_path else None,
            "path_manager_id": path_manager_id or execution_id,
            "test_dir": str(test_dir)
        }
        
        logger.info(f"Test {test_id} completed with status: {status}")
        logger.info(f"Results available at: {test_dir}")
        
        # Archive test results to permanent storage
        try:
            logger.info(f"Archiving test results for test {test_id} in execution {execution_id}")
            
            # Identify the root execution ID (for bulk executions)
            parent_execution_id = path_manager_id or execution_id
            logger.info(f"Parent execution ID for archiving: {parent_execution_id}")
            
            # Check if this is the last test to complete in the execution
            is_last_test = True
            if parent_execution_id in test_executions and 'test_infos' in test_executions[parent_execution_id]:
                # Get total number of tests
                total_tests = len(test_executions[parent_execution_id]['test_infos'])
                completed_tests = 0
                
                # Count completed tests
                for test_info in test_executions[parent_execution_id]['test_infos']:
                    test_info_id = test_info.get('test_id')
                    if test_info_id in test_executions:
                        test_status = test_executions[test_info_id].get('status', None)
                        if test_status in ['completed', 'failed', 'error']:
                            completed_tests += 1
                
                logger.info(f"Execution progress: {completed_tests}/{total_tests} tests completed")
                is_last_test = (completed_tests == total_tests)
            
            # Only archive if this is the last test to complete
            if is_last_test:
                logger.info("This is the last test to complete. Proceeding with archiving...")
                
                # Get the root project directory (one level up from where the script runs)
                project_root = Path(PROJECT_ROOT_DIR)
                logger.info(f"Project root directory: {project_root}")
                
                # Define the permanent storage directory
                perm_storage_dir = project_root / "data" / "manager" / "perm" / "ExecutionResultHistory"
                FileSystemManager.ensure_dir(perm_storage_dir)
                logger.info(f"Permanent storage directory: {perm_storage_dir}")
                
                # Get the execution directory - the source for our copy operation
                if parent_execution_id in test_executions:
                    # Debug what we have in the execution record
                    logger.info(f"Execution record keys: {list(test_executions[parent_execution_id].keys())}")
                    
                    # Try all possible path sources in order of preference
                    exec_root = None
                    
                    # Try exec_path first (should be the most reliable now)
                    if 'exec_path' in test_executions[parent_execution_id]:
                        try:
                            exec_path_str = test_executions[parent_execution_id]['exec_path']
                            exec_root = Path(exec_path_str)
                            logger.info(f"Using path from exec_path: {exec_root}")
                        except Exception as path_error:
                            logger.error(f"Failed to use exec_path: {path_error}")
                    
                    # Try exec_dir as backup
                    if exec_root is None and 'exec_dir' in test_executions[parent_execution_id]:
                        try:
                            exec_dir_str = test_executions[parent_execution_id]['exec_dir']
                            exec_root = Path(exec_dir_str)
                            logger.info(f"Using path from exec_dir: {exec_root}")
                        except Exception as dir_error:
                            logger.error(f"Failed to use exec_dir: {dir_error}")
                            
                    # Try path_manager as a fallback (legacy support)
                    if exec_root is None and 'path_manager' in test_executions[parent_execution_id]:
                        try:
                            path_manager_obj = test_executions[parent_execution_id]['path_manager']
                            exec_root = path_manager_obj.exec_root
                            logger.info(f"Using path from PathManager object: {exec_root}")
                        except Exception as pm_error:
                            logger.error(f"Failed to access path_manager: {pm_error}")
                    
                    # Directly construct the path based on run_id as a last resort
                    else:
                        try:
                            # Use the parent_execution_id directly to match the existing directory format
                            # This ensures we match the UUID-based directory name that was actually created
                            run_id = f"run_{parent_execution_id}"
                            logger.info(f"Using execution ID for run directory name: {run_id}")
                            
                            # As a last resort, grab the run_id directly if stored
                            if 'run_id' in test_executions[parent_execution_id]:
                                run_id = test_executions[parent_execution_id]['run_id']
                                logger.info(f"Found run_id in execution record: {run_id}")
                            
                            # Build the path
                            exec_root = project_root / "data" / "manager" / "exec" / run_id
                            logger.info(f"Using synthesized path from execution ID: {exec_root}")
                        except Exception as synth_error:
                            logger.error(f"Failed to synthesize path: {synth_error}")
                            
                            # As an absolute last resort, scan the exec directory for the matching run folder
                            try:
                                exec_dir = project_root / "data" / "manager" / "exec"
                                if exec_dir.exists() and exec_dir.is_dir():
                                    # Look for a directory that contains the execution ID in its name
                                    for item in exec_dir.iterdir():
                                        if item.is_dir() and parent_execution_id in item.name:
                                            exec_root = item
                                            logger.info(f"Found directory by scanning exec dir: {exec_root}")
                                            break
                                    
                                    if exec_root is None:
                                        logger.error(f"Could not find directory containing execution ID: {parent_execution_id}")
                                        return
                                else:
                                    logger.error(f"Exec directory does not exist: {exec_dir}")
                                    return
                            except Exception as scan_error:
                                logger.error(f"Error scanning for execution directory: {scan_error}")
                                logger.error("No valid path information found in execution record")
                                return
                    
                    # Verify source directory exists
                    if exec_root.exists() and exec_root.is_dir():
                        # Create destination path - use just the run folder name
                        run_dir_name = exec_root.name  # Should be like 'run_YYYYMMDD_HHMMSS'
                        dest_path = perm_storage_dir / run_dir_name
                        
                        # Perform the copy operation
                        if not dest_path.exists():
                            try:
                                logger.info(f"Copying from {exec_root} to {dest_path}")
                                shutil.copytree(exec_root, dest_path)
                                logger.info(f"Successfully archived results to {dest_path}")
                                
                                # Update the execution record
                                test_executions[parent_execution_id]['archived_path'] = str(dest_path)
                                
                                # After successful archiving, clean up the temporary execution directory
                                try:
                                    logger.info(f"Cleaning up temporary execution directory: {exec_root}")
                                    if exec_root.exists() and exec_root.is_dir():
                                        shutil.rmtree(exec_root)
                                        logger.info(f"Successfully removed temporary execution directory: {exec_root}")
                                        # Update execution record to indicate cleanup
                                        test_executions[parent_execution_id]['temp_dir_cleaned'] = True
                                    else:
                                        logger.warning(f"Temporary execution directory does not exist, nothing to clean up: {exec_root}")
                                except Exception as cleanup_error:
                                    logger.error(f"Error cleaning up temporary execution directory: {cleanup_error}")
                                    # Don't fail the archiving if cleanup fails
                            except Exception as copy_error:
                                logger.error(f"Failed to copy execution results: {copy_error}")
                                import traceback
                                logger.error(traceback.format_exc())
                        else:
                            logger.warning(f"Archive destination already exists: {dest_path}")
                    else:
                        logger.error(f"Source directory does not exist: {exec_root}")
                else:
                    logger.error(f"Parent execution record not found: {parent_execution_id}")
            else:
                logger.info("Not the last test to complete. Skipping archiving for now.")
        except Exception as e:
            logger.error(f"Error in archiving process: {str(e)}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Continue with test completion regardless of archiving errors
            
        # No need to clean up - each test has its own dedicated space now
        
    except Exception as e:
        logger.error(f"Error in test execution task: {e}")
        # Update test execution status on error
        test_executions[execution_id] = {
            "test_id": test_id,
            "status": "error",
            "start_time": test_executions[execution_id]["start_time"],
            "end_time": datetime.now().isoformat(),
            "error": str(e)
        }


# API Endpoints

@router.get("/")
async def root():
    """Root endpoint."""
    return {"message": "TestZeus Hercules API Server"}


@router.get("/tests/{execution_id}", response_model=TestResult)
async def get_test_status(execution_id: str):
    """Get the status of a test execution."""
    if execution_id not in test_executions:
        raise HTTPException(status_code=404, detail=f"Test execution {execution_id} not found")
    
    return test_executions[execution_id]

@router.get("/tests")
async def list_tests(status: Optional[str] = None):
    """List all test executions with optional status filter."""
    results = []
    
    for exec_id, test_data in test_executions.items():
        if status is None or test_data.get("status") == status:
            results.append({
                "execution_id": exec_id,
                **test_data
            })
    
    return {"tests": results}

@router.delete("/tests/{execution_id}")
async def delete_test(execution_id: str):
    """Delete a test execution from tracking."""
    if execution_id not in test_executions:
        raise HTTPException(status_code=404, detail=f"Test execution {execution_id} not found")
    
    # Remove from tracking
    del test_executions[execution_id]
    
    # Delete archive if it exists
    archive_dir = PERM_STORAGE_ROOT / execution_id
    if archive_dir.exists():
        try:
            shutil.rmtree(archive_dir)
        except Exception as e:
            logger.error(f"Error deleting archive directory {archive_dir}: {e}")
    
    return {"message": f"Test execution {execution_id} deleted"}

@router.get("/available-tests")
async def list_available_tests():
    """List available test cases."""
    available_tests = []
    
    if INPUT_DIR.exists():
        for item in INPUT_DIR.glob("**/*.feature"):
            relative_path = item.relative_to(INPUT_DIR)
            available_tests.append(str(relative_path))
    
    return {"tests": available_tests}

@router.get("/library")
async def list_library(path: Optional[str] = ""):
    """List contents of the template library directory."""
    try:
        # Resolve the requested path within the library
        target_path = FileSystemManager.safe_path_join(LIBRARY_ROOT, path)
        
        if not target_path.exists():
            return {"error": f"Path '{path}' not found in library"}
            
        if target_path.is_file():
            # If it's a file, return its content
            try:
                with open(target_path, 'r') as f:
                    content = f.read()
                
                return {
                    "type": "file",
                    "name": target_path.name,
                    "path": str(target_path.relative_to(LIBRARY_ROOT)),
                    "content": content
                }
            except Exception as e:
                logger.error(f"Error reading file {target_path}: {e}")
                return {"error": f"Error reading file: {str(e)}"}
        else:
            # If it's a directory, list its contents
            items = []
            for item in target_path.iterdir():
                relative_path = item.relative_to(LIBRARY_ROOT)
                items.append({
                    "name": item.name,
                    "path": str(relative_path),
                    "type": "directory" if item.is_dir() else "file"
                })
            
            # Sort items: directories first, then files
            items.sort(key=lambda x: (0 if x["type"] == "directory" else 1, x["name"]))
            
            return {
                "type": "directory",
                "path": str(target_path.relative_to(LIBRARY_ROOT)),
                "items": items
            }
    except Exception as e:
        logger.error(f"Error listing library contents: {e}")
        return {"error": f"Error listing library: {str(e)}"}


@router.get("/search-library")
async def search_library(query: str):
    """Search for feature files in the library that match a query string."""
    if not query or len(query.strip()) < 3:
        return {"error": "Search query must be at least 3 characters long"}
    
    try:
        # Search in library
        results = APIUtils.search_content(LIBRARY_ROOT, query)
        
        # Return search results
        return {
            "query": query,
            "results": results
        }
    except Exception as e:
        logger.error(f"Error searching library: {e}")
        return {"error": f"Error searching library: {str(e)}"}

@router.get("/archives")
async def list_archives():
    """List available archived test results."""
    archives = []
    
    if PERM_STORAGE_ROOT.exists():
        for item in PERM_STORAGE_ROOT.iterdir():
            if item.is_dir():
                # Try to find test ID and status in the archive
                test_id = None
                status = None
                
                info_file = item / "info.json"
                if info_file.exists():
                    try:
                        with open(info_file, 'r') as f:
                            info = json.load(f)
                            test_id = info.get("test_id")
                            status = info.get("status")
                    except Exception:
                        pass
                
                archives.append({
                    "id": item.name,
                    "path": str(item),
                    "test_id": test_id,
                    "status": status,
                    "created": item.stat().st_mtime
                })
    
    # Sort by creation time, newest first
    archives.sort(key=lambda x: x["created"], reverse=True)
    
    return {"archives": archives}

@router.delete("/archives/{archive_name}")
async def delete_archive(archive_name: str):
    """Delete an archived test result."""
    archive_path = PERM_STORAGE_ROOT / archive_name
    
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail=f"Archive '{archive_name}' not found")
    
    try:
        shutil.rmtree(archive_path)
        return {"message": f"Archive '{archive_name}' deleted successfully"}
    except Exception as e:
        logger.error(f"Error deleting archive {archive_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting archive: {str(e)}")

# Helper function to completely wipe the opt directory
# async def wipe_opt_directory():
#     """Completely wipe and recreate the opt directory structure."""
#     try:
#         # Log the cleanup operation
#         logger.info(f"Completely wiping opt directory: {OPT_DIR}")
#
#         # Check if the directory exists before trying to remove it
#         if OPT_DIR.exists():
#             # Remove the entire directory and its contents
#             shutil.rmtree(OPT_DIR)
#
#         # Recreate the directory structure
#         # FileSystemManager.ensure_dir(OPT_DIR)
#         # FileSystemManager.ensure_dir(INPUT_DIR)
#         # FileSystemManager.ensure_dir(OUTPUT_DIR)
#         # FileSystemManager.ensure_dir(LOG_DIR)
#         # FileSystemManager.ensure_dir(TEST_DATA_DIR)
#         # FileSystemManager.ensure_dir(OPT_DIR / "proofs")
#         # FileSystemManager.ensure_dir(OPT_DIR / "gherkin_files")
#
#         return True
#     except Exception as e:
#         logger.error(f"Error wiping opt directory: {e}")
#         return False

# @router.post("/cleanup")
# async def cleanup_exec():
#     """Clean up all execution directories by completely wiping and recreating the opt directory."""
#     try:
#         # Log the cleaning operation with distinct markers for visibility
#         logger.info(f"[CLEANUP] ===> Starting complete wipe of opt directory: {OPT_DIR}")
#
#         # Remove the entire directory if it exists
#         if OPT_DIR.exists():
#             logger.info(f"[CLEANUP] Directory exists, removing: {OPT_DIR}")
#             shutil.rmtree(OPT_DIR)
#             logger.info(f"[CLEANUP] Successfully removed directory")
#         else:
#             logger.info(f"[CLEANUP] Directory does not exist, nothing to remove")
#
#         # # Recreate the directory structure if needed
#         # logger.info(f"[CLEANUP] Recreating directory structure")
#         # FileSystemManager.ensure_dir(OPT_DIR)
#         # FileSystemManager.ensure_dir(INPUT_DIR)
#         # FileSystemManager.ensure_dir(OUTPUT_DIR)
#         # FileSystemManager.ensure_dir(LOG_DIR)
#         # FileSystemManager.ensure_dir(TEST_DATA_DIR)
#         # FileSystemManager.ensure_dir(OPT_DIR / "proofs")
#         # FileSystemManager.ensure_dir(OPT_DIR / "gherkin_files")
#         # logger.info(f"[CLEANUP] Directory structure recreated successfully")
#
#         # Return success message
#         result = {
#             "message": "Opt directory completely wiped",
#             "status": "success"
#         }
#         logger.info(f"[CLEANUP] ===> Cleanup completed successfully")
#         return result
#
#     except Exception as e:
#         logger.error(f"Error cleaning up execution directories: {e}")
#         raise HTTPException(status_code=500, detail=f"Error during cleanup: {str(e)}")

@router.websocket("/ws/logs")
async def websocket_logs(websocket: WebSocket):
    """WebSocket endpoint for real-time logs from all executions."""
    await websocket_manager.connect(websocket, all_logs=True)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)

@router.websocket("/ws/logs/{execution_id}")
async def websocket_execution_logs(websocket: WebSocket, execution_id: str):
    """WebSocket endpoint for real-time logs from a specific execution."""
    # Validate that execution exists
    if execution_id not in test_executions:
        # Accept connection first so we can send an error message
        await websocket.accept()
        error_msg = json.dumps({
            "type": "error",
            "message": f"Execution ID {execution_id} not found"
        })
        await websocket.send_text(error_msg)
        await websocket.close()
        return
    
    # Connect with the specific execution ID subscription
    await websocket_manager.connect(websocket, execution_id=execution_id)
    
    # Send initial status message
    status_msg = json.dumps({
        "type": "status",
        "execution_id": execution_id,
        "status": test_executions[execution_id].get("status", "unknown"),
        "timestamp": datetime.now().isoformat()
    })
    await websocket.send_text(status_msg)
    
    try:
        while True:
            # Keep the connection open and wait for client messages
            data = await websocket.receive_text()
            
            # Handle client commands if needed
            try:
                command = json.loads(data)
                if command.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)

@router.post("/tests/run-from-template")
async def run_tests_from_template(request: TestInfosRequest, background_tasks: BackgroundTasks):
    """Run tests using templates or scripts from the library.
    Supports both single test mode and bulk test mode.
    
    In bulk mode (EXECUTE_BULK=true), each test gets its own directory under opt/tests/.
    In single mode (default), all tests use the standard opt/ directory structure.
    """
    try:
        # Generate execution record with a unique ID
        execution_id = APIUtils.generate_execution_id()
        start_time = APIUtils.get_timestamp()
        
        # Create a PathManager for this execution
        path_manager = PathManager.create_for_execution(execution_id)
        
        # Log the dynamic execution path
        logger.info(f"Starting new test execution with ID: {execution_id}")
        logger.info(f"Using dynamic execution path: {path_manager.exec_root}")
        
        # Create base directories for this execution
        path_manager.ensure_directories()
        
        # Initialize execution tracking
        exec_path_str = str(path_manager.exec_root)
        logger.info(f"Setting up execution with path: {exec_path_str}")
        
        test_executions[execution_id] = {
            "execution_id": execution_id,
            "status": "pending",
            "start_time": start_time,
            "test_infos": [],
            # Don't store the actual path_manager object as it might not serialize well
            # Instead store all the paths as strings
            "exec_path": exec_path_str,
            "exec_dir": str(path_manager.exec_root),
            "tests_dir": str(path_manager.get_tests_dir()),
            "run_id": path_manager.exec_root.name  # Store the run_id separately for easy reference
        }
        
        # Log path information for debugging
        logger.info(f"Stored exec_path in test_executions[{execution_id}]: {test_executions[execution_id]['exec_path']}")
        logger.info(f"Execution directory structure: {path_manager.exec_root}")
        
        # Handle mock mode
        mock_mode = request.mock
        test_executions[execution_id]["mock"] = mock_mode
        
        # Get paths from path manager
        tests_root = path_manager.get_tests_dir()
        logger.info(f"Created tests directory at {tests_root}")

        # Process each test info
        for info in request.test_infos:
            # Generate a unique test ID for this test
            test_id = f"test_{info.order}"
            
            # Create a test-specific PathManager
            test_path_manager = path_manager.create_for_test(test_id)
            test_path_manager.ensure_directories()
            
            # Get paths for this test
            test_dir = test_path_manager.test_dir
            test_input_dir = test_path_manager.get_input_dir()
            test_output_dir = test_path_manager.get_output_dir()
            test_data_dir = test_path_manager.get_test_data_dir()
            test_logs_dir = test_path_manager.get_logs_dir()
            test_proofs_dir = test_path_manager.get_proofs_dir()
            
            logger.info(f"Created test directory structure for {test_id} at {test_dir}")
            
            # Handle feature template or script
            # When using individual test directories, hercules expects a standard filename: test.feature
            feature_filename = "test.feature"  # Standard filename expected by hercules in non-bulk mode
            library_root = path_manager.get_library_root()
            test_data_library_root = path_manager.get_test_data_library_root()
            
            if info.feature.templatePath:
                feature_path = FileSystemManager.safe_path_join(library_root, info.feature.templatePath, must_exist=True)
                dest_feature = test_input_dir / feature_filename
                shutil.copy2(feature_path, dest_feature)
                logger.info(f"Copied feature template from {feature_path} to {dest_feature}")
            else:
                # Write featureScript to temp file
                temp_dir = library_root / "temp" / execution_id
                FileSystemManager.ensure_dir(temp_dir)
                temp_feature_path = temp_dir / f"{info.order}_temp.feature"
                with open(temp_feature_path, "w", encoding="utf-8") as f:
                    f.write(info.feature.featureScript)
                dest_feature = test_input_dir / feature_filename
                shutil.copy2(temp_feature_path, dest_feature)
                logger.info(f"Created feature script at {dest_feature}")
            
            # Handle test data
            data_paths = []
            if info.testData:
                for td in info.testData:
                    data_src = FileSystemManager.safe_path_join(test_data_library_root, td.templatePath, must_exist=True)
                    dest_data = test_data_dir / data_src.name
                    shutil.copy2(data_src, dest_data)
                    data_paths.append(str(dest_data))
                    logger.info(f"Copied test data from {data_src} to {dest_data}")

            # Record this test info with directory paths
            test_info = {
                "order": info.order,
                "test_id": test_id,
                "headless": info.headless,
                "timeout": info.timeout,
                "test_data": data_paths,
                "path_manager_id": execution_id,  # Reference to the parent execution's PathManager
                "test_dir": str(test_dir),
                "input_dir": str(test_input_dir),
                "output_dir": str(test_output_dir),
                "test_data_dir": str(test_data_dir),
                "logs_dir": str(test_logs_dir),
                "proofs_dir": str(test_proofs_dir)
            }
            
            test_executions[execution_id]["test_infos"].append(test_info)

            # Schedule execution if not mock
            if not mock_mode:
                logger.info(f"Scheduling test execution for {test_id} (headless: {info.headless})")
                
                # Create options dictionary with all the necessary information
                options = {
                    "headless": info.headless,
                    "timeout": info.timeout,
                    "path_manager_id": execution_id,  # So TestTools can recreate the PathManager
                    "test_dir": str(test_dir),
                    "input_dir": str(test_input_dir),
                    "output_dir": str(test_output_dir),
                    "test_data_dir": str(test_data_dir),
                    "logs_dir": str(test_logs_dir),
                    "proofs_dir": str(test_proofs_dir)
                }
                
                background_tasks.add_task(
                    run_test_task,
                    execution_id,
                    test_id,
                    options
                )

        # Handle mock mode: copy mock outputs and return immediately
        if mock_mode:
            mock_output_dir = HERCULES_ROOT / "mockOutput"
            opt_dir = HERCULES_ROOT / "opt"

            # Add mock logs that will be forwarded via WebSocket
            logger.info(f"[MOCK] Starting mock test execution with ID: {execution_id}")
            logger.info(f"[MOCK] Setting up mock environment for test")
            logger.info(f"[MOCK] Preparing to copy mock output from {mock_output_dir}")

            # Save existing inputs
            saved_inputs = {}
            if INPUT_DIR.exists():
                for file in INPUT_DIR.iterdir():
                    if file.is_file():
                        saved_inputs[file.name] = file.read_bytes()
                        logger.info(f"[MOCK] Saved input file: {file.name}")

            # Wipe opt directory
            if opt_dir.exists():
                shutil.rmtree(opt_dir)
                logger.info(f"[MOCK] Cleaned existing opt directory at {opt_dir}")

            # Recreate directory structure
            output_dir = opt_dir / "output"
            input_dir2 = opt_dir / "input"
            test_data_dir = opt_dir / "test_data"
            run_timestamp = APIUtils.format_run_timestamp()
            run_dir = output_dir / f"run_{run_timestamp}"
            FileSystemManager.ensure_dir(output_dir)
            FileSystemManager.ensure_dir(test_data_dir)
            FileSystemManager.ensure_dir(input_dir2)
            FileSystemManager.ensure_dir(run_dir)
            logger.info(f"[MOCK] Created mock run directory: {run_dir}")

            # Restore saved inputs
            for fname, content in saved_inputs.items():
                (input_dir2 / fname).write_bytes(content)
                logger.info(f"[MOCK] Restored input file: {fname}")

            # Ensure test.feature exists
            test_feature_path = input_dir2 / "test.feature"
            if not test_feature_path.exists():
                with open(test_feature_path, "w", encoding="utf-8") as f:
                    f.write("# Empty test file created during mock mode")
                logger.info(f"[MOCK] Created empty test feature file at {test_feature_path}")

            # Update all test_ids to test.feature
            for ti in test_executions[execution_id]["test_infos"]:
                ti["test_id"] = "test.feature"

            # Copy required mock directories
            required_dirs = ["gherkin_files", "log_files", "proofs","output"]
            if mock_output_dir.exists():
                for dir_name in required_dirs:
                    src_dir = mock_output_dir / dir_name
                    dst_dir = opt_dir / dir_name
                    if src_dir.exists():
                        if dst_dir.exists():
                            shutil.rmtree(dst_dir)
                        shutil.copytree(src_dir, dst_dir)
                        logger.info(f"[MOCK] Copied mock directory: {dir_name}")
                    else:
                        FileSystemManager.ensure_dir(dst_dir)
                        logger.info(f"[MOCK] Created empty directory: {dir_name}")

                # Copy mock test_data
                test_data_mock = mock_output_dir / "test_data"
                if test_data_mock.exists():
                    for item in test_data_mock.iterdir():
                        dst = test_data_dir / item.name
                        if item.is_dir():
                            if dst.exists(): shutil.rmtree(dst)
                            shutil.copytree(item, dst)
                        else:
                            shutil.copy2(item, dst)
                    logger.info(f"[MOCK] Copied mock test data from {test_data_mock}")

                # Generate simulated test execution logs
                for i in range(5):
                    logger.info(f"[MOCK TEST] Executing step {i+1}/5 of test scenario")
                    # Add small delay to make logs appear more realistic
                    await asyncio.sleep(0.2)
                
                logger.info(f"[MOCK TEST] All steps executed successfully")
                logger.info(f"[MOCK TEST] Test execution completed with status: PASSED")
                logger.info(f"[MOCK] Mock test execution completed for ID: {execution_id}")

                # Finalize mock execution record
                test_executions[execution_id]["status"] = "completed"
                test_executions[execution_id]["end_time"] = APIUtils.get_timestamp()
                test_executions[execution_id]["result"] = {"status": "mocked", "output_dir": str(run_dir)}
                run_dir = OUTPUT_DIR / f"run_{APIUtils.format_run_timestamp()}"
                archive_path = await archive_test_results(execution_id, test_id, OPT_DIR)
                logger.info("HI IS THIS RUN ? ")
                cleanup_result = await cleanup_exec()
                logger.info(f"===> Cleanup completed with result: {cleanup_result}")

                return {"execution_id": execution_id, "status": "mocked", "start_time": start_time, "output_dir": str(run_dir)}
            else:
                # No mock output dir found
                logger.warning(f"[MOCK] Mock output directory not found at {mock_output_dir}")
                test_executions[execution_id]["status"] = "mocked"
                test_executions[execution_id]["end_time"] = APIUtils.get_timestamp()
                test_executions[execution_id]["result"] = {"status": "mocked"}
                return {"execution_id": execution_id, "status": "mocked", "start_time": start_time}
        # More detailed logging before cleanup
        # logger.info(f"===> Starting cleanup before running test execution_id={execution_id}")
        # cleanup_result = await cleanup_exec()
        # logger.info(f"===> Cleanup completed with result: {cleanup_result}")
        # Default response for scheduled tasks
        return {"execution_id": execution_id, "status": "pending", "start_time": start_time}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error running tests from templates: {str(e)}")

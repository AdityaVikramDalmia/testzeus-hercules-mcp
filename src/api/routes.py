#!/usr/bin/env python
import os
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Tuple
import asyncio
import uuid

from fastapi import APIRouter, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

# Change import from server to app
from app import app
from src.api.models import TestRequest, TestInfosRequest, TestResponse, TestResult, HFileRequest
from src.api.utils import APIUtils
from src.utils.filesystem import FileSystemManager
from src.utils.logger import logger
from src.utils.config import Config
from src.utils.path_manager import PathManager
from src.utils.database import Database
from src.tools.test_tools import TestTools
from src.tools.test_utils import TestUtils

# Create router
router = APIRouter()

# Get configuration and directory paths
dirs = Config.get_data_directories()
exec_config = Config.get_test_execution_config()

# Initialize database for tracking test executions
db = Database()

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

# Load existing executions from database on startup
def load_executions_from_db():
    """Load all executions from database into memory on server startup."""
    try:
        db_executions = db.get_all_executions()
        for exec_data in db_executions:
            exec_id = exec_data.get("execution_id")
            if exec_id:
                # Extract metadata if available
                metadata = exec_data.get("metadata")
                if isinstance(metadata, str):
                    try:
                        metadata = json.loads(metadata)
                    except:
                        metadata = {}
                
                # Create a basic record
                test_executions[exec_id] = {
                    "status": exec_data.get("status", "unknown"),
                    "start_time": exec_data.get("start_time"),
                    "end_time": exec_data.get("end_time"),
                    "completed_tests": metadata.get("completed_tests", 0) if metadata else 0,
                    "total_tests": metadata.get("total_tests", 0) if metadata else 0,
                    "failed_tests": metadata.get("failed_tests", 0) if metadata else 0,
                    "test_infos": metadata.get("test_infos", []) if metadata else []
                }
        logger.info(f"Loaded {len(db_executions)} executions from database")
    except Exception as e:
        logger.error(f"Error loading executions from database: {e}")

# Load executions at startup
load_executions_from_db()

# Import the WebSocket connection manager from the dedicated module
from src.api.websocket import manager as websocket_manager

# Function to ensure database is properly flushed after operations
def ensure_db_flushed():
    """Ensure database changes are flushed to disk."""
    try:
        db.flush()
    except Exception as e:
        logger.error(f"Error flushing database: {e}")

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
    """Run a single test as a background task.

    Args:
        execution_id: ID of the overall execution
        test_id: ID of the test to run
        options: Additional test options
    """
    try:
        # Get starting time
        start_time = APIUtils.get_timestamp()

        # Record test start in database
        metadata = {
            'execution_id': execution_id,
            'options': options if options else {}
        }

        # Record as JSON string for database storage
        metadata_json = json.dumps(metadata)

        # Create run in database with initial state
        try:
            # Extract browser info from options for database
            browser_type = options.get('browser', 'chromium') if options else 'chromium'
            headless = options.get('headless', False) if options else False
            environment = options.get('environment', 'test') if options else 'test'

            # Create the run record
            db_run_id = db.create_run(
                test_id=test_id,
                browser_type=browser_type,
                headless=headless,
                environment=environment,
                metadata=metadata_json
            )
            logger.info(f"Created database record for test run: {db_run_id}")
            ensure_db_flushed()
        except Exception as db_error:
            logger.error(f"Failed to record test start in database: {db_error}")
            # Continue with execution even if database recording fails

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
        # Use configurable environment file path
        from src.utils.paths import get_env_file_path
        env_file = str(get_env_file_path())
        
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
            
        logger.info(f"Test {test_id} for execution {execution_id} completed with status: {status}")
        
        # Generate a timestamp for this run
        run_timestamp = APIUtils.format_run_timestamp()
        
        # Results are in the dynamic test directory
        run_dir = test_output_dir / f"run_{run_timestamp}"
        archive_path = test_dir
            
        # Update test execution status
        end_time = datetime.now().isoformat()
        
        # Always update local test_executions entry and database
        test_executions[execution_id] = {
            "execution_id": execution_id,
            "test_id": test_id,
            "status": status,
            "start_time": start_time,
            "end_time": end_time,
            "result": result_data
        }
        
        # Get test run matching this execution from database
        try:
            # Find any existing run_id for this test
            existing_runs = db.get_runs_by_test_id(test_id)
            
            # Look for a run that matches this execution
            matching_run = None
            for run in existing_runs:
                metadata = run.get('metadata')
                if isinstance(metadata, dict) and metadata.get('execution_id') == execution_id:
                    matching_run = run
                    break
            
            if matching_run:
                # Update the correct run record for this execution
                db_run_id = matching_run['id']
                # Update the status and end time
                logger.info(f"Updating database record ID {db_run_id} for test {test_id} with status: {status}")
                db.update_run_status(db_run_id, status, end_time)
                
                # Save detailed result metadata as an event
                if result_data and isinstance(result_data, dict):
                    # Convert any Path objects to strings
                    json_safe_result = path_to_json(result_data)
                    event_data = json.dumps(json_safe_result)
                    db.create_event(db_run_id, None, "test_result", 
                                  f"Test {test_id} {status}", event_data)
                    
                    # If there were steps recorded in the test, add them to the database
                    if 'steps' in result_data and isinstance(result_data['steps'], list):
                        for i, step_data in enumerate(result_data['steps']):
                            try:
                                step_desc = step_data.get('description', f'Step {i+1}')
                                step_status = step_data.get('status', 'unknown')
                                step_id = db.create_step(db_run_id, i+1, step_desc)
                                db.update_step_status(step_id, step_status)
                                
                                # Add step details as an event - ensure Path objects are converted
                                json_safe_step = path_to_json(step_data)
                                db.create_event(db_run_id, step_id, "step_details",
                                              f"Step {i+1}: {step_status}", json.dumps(json_safe_step))
                            except Exception as step_error:
                                logger.error(f"Error recording step {i+1} in database: {step_error}")
                
                logger.info(f"Updated database record for run ID {db_run_id} with status: {status}")
            else:
                # No matching record found for this execution, create a new one
                logger.warning(f"No matching database record found for test {test_id} in execution {execution_id}. Creating new record.")
                try:
                    # Extract browser info from options for database
                    browser_type = options.get('browser', 'chromium') if options else 'chromium'
                    headless = options.get('headless', False) if options else False
                    environment = options.get('environment', 'test') if options else 'test'
                    
                    # Create metadata for database
                    metadata = {
                        'execution_id': execution_id,
                        'path_manager_id': path_manager_id,
                        'test_dir': str(test_dir),
                        'options': options if options else {}
                    }
                    
                    # Create a run record with completed status
                    db_run_id = db.create_run(
                        test_id=test_id,
                        browser_type=browser_type,
                        headless=headless,
                        environment=environment,
                        metadata=json.dumps(metadata),
                        status=status,
                        start_time=start_time,
                        end_time=end_time
                    )
                    logger.info(f"Created database record for completed test: {db_run_id}")
                    
                    # Also record the result as an event
                    if result_data and isinstance(result_data, dict):
                        # Convert any Path objects to strings
                        json_safe_result = path_to_json(result_data)
                        event_data = json.dumps(json_safe_result)
                        db.create_event(db_run_id, None, "test_result", 
                                      f"Test {test_id} {status}", event_data)
                except Exception as create_error:
                    logger.error(f"Error creating test record in database: {create_error}")
        except Exception as db_error:
            logger.error(f"Failed to record test completion in database: {db_error}")
            # Continue execution even if database update fails
        
        # Automatically process XML results when test is completed
        try:
            # Only process if test status indicates completion
            if status in ["completed", "failed", "error"]:
                logger.info(f"Test {test_id} {status}, automatically processing XML results")
                processed_count, error_count = await process_xml_directly(execution_id, test_id)
                
                if processed_count > 0:
                    logger.info(f"Automatically processed {processed_count} XML files for execution {execution_id}, test {test_id}")
                else:
                    logger.warning(f"No XML results found for test {test_id} in execution {execution_id}")
        except Exception as xml_error:
            logger.error(f"Error auto-processing XML results for test {test_id}: {xml_error}")
            # Continue with execution flow even if XML processing fails
        
        # Update the parent execution status in memory and database
        # Check if parent execution ID exists
        parent_execution_id = path_manager_id or execution_id
        if parent_execution_id in test_executions:
            # Then check if this is a parent execution with test_infos
            if 'test_infos' in test_executions[parent_execution_id]:
                logger.info(f"Updating parent execution {parent_execution_id} status after test {test_id} completed with {status}")
                
                try:
                    # Get all test infos from the parent execution
                    parent_test_infos = test_executions[parent_execution_id].get('test_infos', [])
                    total_tests = len(parent_test_infos)
                    completed_tests = 0
                    failed_tests = 0
                    
                    # Check status of all tests in this execution
                    for test_info in parent_test_infos:
                        test_info_id = test_info.get('test_id')
                        if test_info_id in test_executions:
                            test_status = test_executions[test_info_id].get('status', None)
                            if test_status in ['completed', 'failed', 'error']:
                                completed_tests += 1
                                if test_status in ['failed', 'error']:
                                    failed_tests += 1
                    
                    # Determine overall execution status
                    if completed_tests == total_tests:
                        # All tests are done
                        parent_status = "failed" if failed_tests > 0 else "completed"
                        parent_end_time = datetime.now().isoformat()
                        
                        # Update parent execution record in memory
                        test_executions[parent_execution_id]['status'] = parent_status
                        test_executions[parent_execution_id]['end_time'] = parent_end_time
                        test_executions[parent_execution_id]['completed_tests'] = completed_tests
                        test_executions[parent_execution_id]['failed_tests'] = failed_tests
                        
                        # Update execution record in database
                        db.update_execution_status(parent_execution_id, parent_status, parent_end_time)
                        ensure_db_flushed()
                        logger.info(f"All tests completed. Updated parent execution {parent_execution_id} status to {parent_status}")
                    else:
                        # Some tests still running
                        progress = f"{completed_tests}/{total_tests}"
                        logger.info(f"Execution {parent_execution_id} progress: {progress} tests completed")
                        
                        # Update progress in memory
                        test_executions[parent_execution_id]['completed_tests'] = completed_tests
                        test_executions[parent_execution_id]['failed_tests'] = failed_tests
                        
                        # Update progress in database
                        try:
                            # Update the execution metadata to include progress
                            execution_record = db.get_execution(parent_execution_id)
                            if execution_record:
                                # Parse metadata
                                metadata = execution_record.get('metadata')
                                if isinstance(metadata, str):
                                    metadata = json.loads(metadata)
                                elif metadata is None:
                                    metadata = {}
                                    
                                # Update metadata with test statistics
                                metadata.update({
                                    'progress': f"{completed_tests}/{total_tests}",
                                    'completed_tests': completed_tests,
                                    'failed_tests': failed_tests
                                })
                                
                                # Ensure database record is updated
                                db.update_execution_status(parent_execution_id, "running", None)
                        except Exception as e:
                            logger.error(f"Error updating execution progress: {e}")
                except Exception as e:
                    logger.error(f"Error updating parent execution status: {e}")
            
        # Archive test results to permanent storage
        try:
            logger.info(f"Archiving test results for test {test_id} in execution {execution_id}")
            
            # Identify the root execution ID (for bulk executions)
            parent_execution_id = path_manager_id or execution_id
            logger.info(f"Parent execution ID for archiving: {parent_execution_id}")
            
            # Check if this is the last test to complete
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
                
                # Get the root project directory
                project_root = Path(PROJECT_ROOT_DIR)
                logger.info(f"Project root directory: {project_root}")
                
                # Define the permanent storage directory
                # Use the paths utility to get the proper base directory
                from src.utils.paths import get_data_dir
                data_dir = get_data_dir()
                perm_storage_dir = data_dir / "manager" / "perm" / "ExecutionResultHistory"
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
                            
                            # Build the path - use get_data_dir() to handle DATA_DIR correctly
                            from src.utils.paths import get_data_dir
                            data_dir = get_data_dir()
                            exec_root = data_dir / "manager" / "exec" / run_id
                            logger.info(f"Using synthesized path from execution ID: {exec_root}")
                        except Exception as synth_error:
                            logger.error(f"Failed to synthesize path: {synth_error}")
                            
                            # As an absolute last resort, scan the exec directory for the matching run folder
                            try:
                                from src.utils.paths import get_data_dir
                                data_dir = get_data_dir()
                                exec_dir = data_dir / "manager" / "exec"
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
                        
                        # Prepare for cleanup function - define it here so we can reuse it
                        def cleanup_temp_directory():
                            try:
                                logger.info(f"Cleaning up temporary execution directory: {exec_root}")
                                if exec_root.exists() and exec_root.is_dir():
                                    shutil.rmtree(exec_root)
                                    logger.info(f"Successfully removed temporary execution directory: {exec_root}")
                                    # Update execution record to indicate cleanup
                                    test_executions[parent_execution_id]['temp_dir_cleaned'] = True
                                    return True
                                else:
                                    logger.warning(f"Temporary execution directory does not exist, nothing to clean up: {exec_root}")
                                    return False
                            except Exception as cleanup_error:
                                logger.error(f"Error cleaning up temporary execution directory: {cleanup_error}")
                                # Don't fail the archiving if cleanup fails
                                return False
                        
                        # Perform the copy operation if needed
                        archive_exists = dest_path.exists()
                        
                        if not archive_exists:
                            try:
                                logger.info(f"Copying from {exec_root} to {dest_path}")
                                shutil.copytree(exec_root, dest_path)
                                logger.info(f"Successfully archived results to {dest_path}")
                                
                                # Update the execution record
                                test_executions[parent_execution_id]['archived_path'] = str(dest_path)
                                
                                # After successful archiving, ensure execution status is updated
                                try:
                                    parent_test_infos = test_executions[parent_execution_id].get('test_infos', [])
                                    total_tests = len(parent_test_infos)
                                    completed_tests = 0
                                    failed_tests = 0
                                    
                                    # Check status of all tests in this execution
                                    for test_info in parent_test_infos:
                                        test_info_id = test_info.get('test_id')
                                        if test_info_id in test_executions:
                                            test_status = test_executions[test_info_id].get('status', None)
                                            if test_status in ['completed', 'failed', 'error']:
                                                completed_tests += 1
                                                if test_status in ['failed', 'error']:
                                                    failed_tests += 1
                                    
                                    # Force status update if all tests are done
                                    if completed_tests == total_tests:
                                        execution_status = "failed" if failed_tests > 0 else "completed"
                                        end_time = datetime.now().isoformat()
                                        
                                        # Update execution status
                                        test_executions[parent_execution_id]['status'] = execution_status
                                        test_executions[parent_execution_id]['end_time'] = end_time
                                        test_executions[parent_execution_id]['completed_tests'] = completed_tests
                                        test_executions[parent_execution_id]['failed_tests'] = failed_tests
                                        
                                        # Update database
                                        db.update_execution_status(parent_execution_id, execution_status, end_time)
                                        ensure_db_flushed()
                                        logger.info(f"Updated execution status to {execution_status} after archiving")
                                except Exception as status_error:
                                    logger.error(f"Error updating execution status after archiving: {status_error}")
                                
                                # After successful archiving, clean up the temporary execution directory
                                cleanup_temp_directory()
                            except Exception as copy_error:
                                logger.error(f"Failed to copy execution results: {copy_error}")
                                import traceback
                                logger.error(traceback.format_exc())
                        else:
                            logger.warning(f"Archive destination already exists: {dest_path}")
                            # Even though we didn't create a new archive, we should still clean up
                            # First verify the archive is valid by checking that it contains expected files
                            if dest_path.exists() and dest_path.is_dir() and any(dest_path.iterdir()):
                                logger.info(f"Archive exists and appears valid, proceeding with cleanup")
                                # Mark that we found the archived path
                                test_executions[parent_execution_id]['archived_path'] = str(dest_path)
                                # Clean up the temporary directory
                                cleanup_temp_directory()
                            else:
                                logger.error(f"Archive exists but appears invalid - won't clean up temp directory")
                        
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
        
        # Update database with error status
        try:
            # Try to find the test run in the database
            run_records = db.get_runs_by_test_id(test_id)
            matching_run = None
            
            for run in run_records:
                try:
                    metadata = run.get('metadata')
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    
                    if metadata and metadata.get('execution_id') == execution_id:
                        matching_run = run
                        break
                except:
                    continue
            
            if matching_run:
                db_run_id = matching_run['id']
                end_time = datetime.now().isoformat()
                db.update_run_status(db_run_id, "error", end_time)
                
                # Record error details as an event
                db.create_event(db_run_id, None, "error", f"Test execution error: {str(e)}")
                logger.info(f"Updated test run {db_run_id} status to error in database")
        except Exception as db_error:
            logger.error(f"Error updating test status in database: {db_error}")
        
        # Check if we need to update parent execution status
        try:
            parent_execution_id = path_manager_id or execution_id
            if parent_execution_id in test_executions:
                # Check if this is a parent execution with test_infos
                if 'test_infos' in test_executions[parent_execution_id]:
                    # Similar logic as above to recalculate parent execution status
                    # but we know at least this test has failed
                    parent_test_infos = test_executions[parent_execution_id].get('test_infos', [])
                    total_tests = len(parent_test_infos)
                    completed_tests = 0
                    failed_tests = 1  # At least this test has failed
                    
                    for test_info in parent_test_infos:
                        test_info_id = test_info.get('test_id')
                        if test_info_id != test_id and test_info_id in test_executions:  # Skip the current test
                            test_status = test_executions[test_info_id].get('status', None)
                            if test_status in ['completed', 'failed', 'error']:
                                completed_tests += 1
                                if test_status in ['failed', 'error']:
                                    failed_tests += 1
                    
                    completed_tests += 1  # Count this test as completed (with error)
                    
                    if completed_tests == total_tests:
                        # All tests are done, and we know at least this one failed
                        parent_status = "failed"
                        parent_end_time = datetime.now().isoformat()
                        
                        # Update parent execution record
                        test_executions[parent_execution_id]['status'] = parent_status
                        test_executions[parent_execution_id]['end_time'] = parent_end_time
                        test_executions[parent_execution_id]['completed_tests'] = completed_tests
                        test_executions[parent_execution_id]['failed_tests'] = failed_tests
                        
                        # Update execution in database
                        db.update_execution_status(parent_execution_id, parent_status, parent_end_time)
                        ensure_db_flushed()
                        logger.info(f"Updated parent execution {parent_execution_id} status to failed after test error")
        except Exception as update_error:
            logger.error(f"Error updating parent execution after test error: {update_error}")


# API Endpoints

@router.get("/", operation_id="main_op")
async def root():
    """Root endpoint."""
    return {"message": "TestZeus Hercules API Server"}

@router.get("/executions/{execution_id}", response_model=dict, operation_id="getExecutionDetails")
async def get_execution_status(execution_id: str):
    """
    Returns comprehensive details about a test execution including status, progress, and results.

      Provides:
      - Execution status (pending/running/completed/failed)
      - Test progress (completed_tests/total_tests)
      - XML result analysis with pass/fail status
      - Database records of all test runs with steps and events
      - Test artifacts (screenshots, logs, proofs)

      Use this to monitor execution progress and analyze results after completion.
        FOR GETTING ALL EXECUTIONS, DO NOT PASS A PAYLOAD
      Example response structure:
      ```json
      {
        "execution_id": "12345-uuid",
        "status": "completed",
        "test_passed": true,
        "test_summary": "All tests passed successfully",
        "xml_results": [...],
        "database_records": [...],
        "completed_tests": 3,
        "total_tests": 3
      }
      ```
    """
    if execution_id not in test_executions:
        raise HTTPException(status_code=404, detail=f"Execution ID {execution_id} not found")
        
    execution = test_executions[execution_id]
    
    # Get XML test results from database for this execution
    xml_results = []
    test_passed = None
    test_summary = ""
    try:
        xml_results = db.get_xml_test_results(execution_id)
        
        # Determine overall test pass/fail status from XML results
        if xml_results:
            # Default to True - we'll set to False if any tests failed
            all_tests_passed = True
            test_count = len(xml_results)
            passed_count = 0
            
            # Check each XML result
            for result in xml_results:
                if 'test_passed' in result and result['test_passed'] is not None:
                    if result['test_passed']:
                        passed_count += 1
                    else:
                        all_tests_passed = False
            
            # Set overall status
            test_passed = all_tests_passed if test_count > 0 else None
            
            # Create summary
            if test_count > 0:
                if test_count == 1:
                    # For a single test, include the final response if available
                    single_result = xml_results[0]
                    final_response = single_result.get('final_response', '')
                    if final_response and len(final_response) > 0:
                        test_summary = final_response
                    else:
                        test_summary = f"Test {'passed' if test_passed else 'failed'}"
                else:
                    # For multiple tests, show summary statistics
                    test_summary = f"{passed_count} of {test_count} tests passed"
                    
            logger.info(f"Execution {execution_id} test status: {test_passed}, summary: {test_summary}")
    except Exception as e:
        logger.error(f"Error retrieving XML results for execution {execution_id}: {e}")
    
    return {
        "execution_id": execution_id,
        "status": execution.get("status", "unknown"),
        "start_time": execution.get("start_time"),
        "end_time": execution.get("end_time"),
        "test_passed": test_passed,
        "test_summary": test_summary,
        "xml_results": xml_results,
        "xml_results_count": len(xml_results)
    }

@router.get("/executions/{execution_id}/details", response_model=dict)
async def get_execution_details(execution_id: str):
    """Get detailed information about a test execution including database records.
    
    Args:
        execution_id: ID of the execution
        
    Returns:
        Detailed information including:
        - Test execution status from in-memory state
        - Database records of all tests associated with this execution
    """
    logger.debug(f"Getting execution details: {execution_id}")
    
    try:
        # Check if execution exists in memory
        if execution_id not in test_executions:
            logger.warning(f"Execution {execution_id} not found in memory")
            return {"error": f"Execution {execution_id} not found"}
            
        execution = test_executions[execution_id]
        
        # Get execution record from database
        db_execution = db.get_execution(execution_id)
        
        # Create the response object with combined data from memory and database
        response = {
            "execution_id": execution_id,
            "status": execution.get("status", "unknown"),
            "start_time": execution.get("start_time", ""),
            "end_time": execution.get("end_time", ""),
            "test_count": len(execution.get("test_infos", [])) if "test_infos" in execution else 0,
            "completed_tests": execution.get("completed_tests", 0),
            "failed_tests": execution.get("failed_tests", 0),
            "test_infos": execution.get("test_infos", []),
            "database_execution": db_execution,
            "database_records": []
        }
        
        # Get all tests associated with this execution from the database
        matching_runs = []
        try:
            # First attempt to get directly from execution_id
            runs = db.get_runs_by_execution_id(execution_id)
            if runs:
                matching_runs.extend(runs)
                
            # Then try to get any runs that have this execution_id in their metadata
            all_runs = db.get_all_runs()
            for run in all_runs:
                try:
                    # Check if this run has an execution_id in metadata
                    metadata = run.get("metadata", "{}")
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                        
                    if isinstance(metadata, dict) and metadata.get("execution_id") == execution_id:
                        # Check if this run is already in matching_runs
                        if not any(r.get("id") == run.get("id") for r in matching_runs):
                            matching_runs.append(run)
                except json.JSONDecodeError:
                    continue  # Skip runs with invalid JSON metadata
                except Exception as metadata_error:
                    logger.error(f"Error processing run metadata: {metadata_error}")
        except Exception as db_error:
            logger.error(f"Error retrieving runs from database: {db_error}")
            
        # Process each matching run to include in the response
        for run in matching_runs:
            # Convert run to a JSON-serializable dictionary
            test_record = dict(run)
            
            try:
                # Get all steps for this run
                if "id" in run:
                    steps = db.get_steps_by_run_id(run["id"])
                    test_record["steps"] = [dict(step) for step in steps]
            except Exception as steps_error:
                logger.error(f"Error retrieving steps for run {run.get('id')}: {steps_error}")
                test_record["steps"] = []
                
            # Add the record to the response
            response["database_records"].append(test_record)
            
        # Add database record count to the response
        response["total_database_records"] = len(matching_runs)
        
        # Get XML test results
        try:
            xml_results = db.get_xml_test_results(execution_id)
            response["xml_results"] = xml_results
            response["total_xml_results"] = len(xml_results)
        except Exception as xml_error:
            logger.error(f"Error retrieving XML results: {xml_error}")
            response["xml_results"] = []
            response["total_xml_results"] = 0
        
        return response
    except Exception as e:
        logger.error(f"Error retrieving execution details from database: {e}")
        # Return basic info even if database query fails
        response = {
            "execution_id": execution_id,
            "database_error": str(e)
        }
        
        if execution_id in test_executions:
            for key, value in test_executions[execution_id].items():
                if key != "path_manager":  # Skip path_manager as it's not JSON serializable
                    response[key] = value
                    
        return response

@router.get("/executions/{execution_id}/xml-results", response_model=dict)
async def get_execution_xml_results(execution_id: str, test_id: Optional[str] = None):
    """Get XML test results for an execution.
    
    Args:
        execution_id: ID of the execution
        test_id: Optional - filter by test ID
        
    Returns:
        XML test results
    """
    logger.debug(f"Getting XML results for execution: {execution_id}, test: {test_id or 'all'}")
    
    try:
        # Get XML test results from database
        xml_results = db.get_xml_test_results(execution_id, test_id)
        
        # Format the response
        response = {
            "execution_id": execution_id,
            "test_id": test_id,
            "total_results": len(xml_results),
            "results": xml_results
        }
        
        return response
    except Exception as e:
        logger.error(f"Error retrieving XML results: {e}")
        return {
            "execution_id": execution_id,
            "test_id": test_id,
            "error": str(e),
            "results": []
        }

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
#         # Check if directory exists before trying to remove it
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

@app.get("/test/checking", operation_id="getTestChecking")
async def get_test_checking():
    """
    Gets a ping check on the server
    Returns a ping check on the server
    """
    return {"message": "pong"}

@app.post("/tests/run-from-template-new", operation_id="runningATemplate")
async def run_tests_from_template(request: TestInfosRequest, background_tasks: BackgroundTasks):
    """
      Execute one or more tests using templates or scripts from the library. This endpoint provides comprehensive test execution capabilities with real-time monitoring.

      ## Core Capabilities
      - Execute tests using feature templates from the library (Gherkin format)
      - Provide custom feature scripts directly for one-off tests
      - Use test data templates with variable substitution
      - Configure browser settings (headless mode, browser type)
      - Set execution timeouts and environment-specific configurations
      - Run in mock mode for testing without actual execution
      - Track execution progress with unique execution IDs

      ## Template Path Configuration
      All template paths are relative to system library directories:
      - **Feature templates**: `data/manager/lib/features/` (e.g., "basic/test.feature")
      - **Test data templates**: `data/manager/lib/test_data/` (e.g., "credentials.txt")

      ## Request Structure
      **Required Fields:**
      - `test_infos` (array): Array of test configurations
        - `order` (integer): Execution sequence (0-based, tests run sequentially)
        - `feature` (object): Either `templatePath` OR `featureScript` (mutually exclusive)
          - `templatePath`: Path to library template relative to features directory
          - `featureScript`: Custom Gherkin script for one-off tests

      **Optional Fields per test:**
      - `testData` (array): Test data templates for variable substitution
      - `headless` (boolean, default: false): Browser visibility (true for CI/CD)
      - `timeout` (integer, default: 300): Max execution time in seconds (1-3600)
      - `browser` (string, default: "chromium"): Browser engine ("chromium", "firefox", "webkit")


      ## Response Structure
      Returns immediately with:
      - `execution_id`: Unique UUID for tracking progress
      - `status`: "pending" (scheduled), "running" (executing), or "mocked" (simulated)
      - `start_time`: ISO timestamp of execution creation
      - `message`: Human-readable status message
      - `wsUrl`: WebSocket URL to receive real-time logs for this execution. Useful for observing execution progress in a separate terminal or IDE. THIS SHOULD BE UTILISED TO MONITOR IN BACKGROUND. COMMAND CAN WE BUSED IWTH SOCAT like  websocat ws://127.0.0.1:8003/ws/logs/13db9744-abe6-4947-80cc-8612a91a0e21
      ## Example Usage
      ```json
      [
          {
            "order": 0,
            "feature": {
              "templatePath": "login/oauth.feature"
            },
            "testData": [
              {"templatePath": "prod_credentials.txt"}
            ],
            "headless": true,
            "timeout": 600,
            "browser": "chromium"
          },
          {
            "order": 1,
            "feature": {
              "featureScript": "Feature: Custom Test\n  Scenario: Verify endpoint\n    Given I have API access\n    When I call the endpoint\n    Then I get success response"
            },
            "browser": "firefox"
          }
        ]
      ```

      ## Test Data Variable Substitution
      Test data files contain key-value pairs (e.g., `username=admin&password=secret123`) that get substituted into feature scripts using `${variable}` syntax in Gherkin steps.

      ## Execution Flow
      1. Submit test configuration to get unique execution_id
      2. Tests execute sequentially by order value
      3. Monitor progress using execution_id with other endpoints
      4. Retrieve results and artifacts when complete

      ## Error Responses
      - **400**: Invalid request (missing required fields, invalid configuration)
      - **500**: Server error (infrastructure issues, database failures)

      ## Integration Notes
      - Use `getAllContent` operationId to discover available templates
      - Execution runs asynchronously - use execution_id for status checks
      - Mock mode useful for testing configurations without resource usage
      - Results include detailed XML analysis and test artifacts
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

        # Create execution record in database
        execution_metadata = {
            "total_tests": len(request.test_infos),
            "mock": request.mock,
            "exec_path": exec_path_str
        }
        db.create_execution(execution_id, "pending", execution_metadata)
        logger.info(f"Created database record for execution: {execution_id}")

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


                # Use asyncio.create_task instead of background_tasks.add_task
                asyncio.create_task(
                    run_test_task(
                        execution_id,
                        test_id,
                        options
                    )
                )

                # background_tasks.add_task(
                #     run_test_task,
                #     execution_id,
                #     test_id,
                #     options
                # )

        # Update execution status to running once all tests are scheduled
        if not mock_mode:
            test_executions[execution_id]["status"] = "running"
            db.update_execution_status(execution_id, "running")
            logger.info(f"Updated execution status to running: {execution_id}")

        # Handle mock mode: copy mock outputs and return immediately
        # if mock_mode:
        #     mock_output_dir = HERCULES_ROOT / "mockOutput"
        #     opt_dir = HERCULES_ROOT / "opt"
        #
        #     # Add mock logs that will be forwarded via WebSocket
        #     logger.info(f"[MOCK] Starting mock test execution with ID: {execution_id}")
        #     logger.info(f"[MOCK] Setting up mock environment for test")
        #     logger.info(f"[MOCK] Preparing to copy mock output from {mock_output_dir}")
        #
        #     # Save existing inputs
        #     saved_inputs = {}
        #     if INPUT_DIR.exists():
        #         for file in INPUT_DIR.iterdir():
        #             if file.is_file():
        #                 saved_inputs[file.name] = file.read_bytes()
        #                 logger.info(f"[MOCK] Saved input file: {file.name}")
        #
        #     # Wipe opt directory
        #     if opt_dir.exists():
        #         shutil.rmtree(opt_dir)
        #         logger.info(f"[MOCK] Cleaned existing opt directory at {opt_dir}")
        #
        #     # Recreate directory structure
        #     output_dir = opt_dir / "output"
        #     input_dir2 = opt_dir / "input"
        #     test_data_dir = opt_dir / "test_data"
        #     run_timestamp = APIUtils.format_run_timestamp()
        #     run_dir = output_dir / f"run_{run_timestamp}"
        #     FileSystemManager.ensure_dir(output_dir)
        #     FileSystemManager.ensure_dir(test_data_dir)
        #     FileSystemManager.ensure_dir(input_dir2)
        #     FileSystemManager.ensure_dir(run_dir)
        #     logger.info(f"[MOCK] Created mock run directory: {run_dir}")
        #
        #     # Restore saved inputs
        #     for fname, content in saved_inputs.items():
        #         (input_dir2 / fname).write_bytes(content)
        #         logger.info(f"[MOCK] Restored input file: {fname}")
        #
        #     # Ensure test.feature exists
        #     test_feature_path = input_dir2 / "test.feature"
        #     if not test_feature_path.exists():
        #         with open(test_feature_path, "w", encoding="utf-8") as f:
        #             f.write("# Empty test file created during mock mode")
        #         logger.info(f"[MOCK] Created empty test feature file at {test_feature_path}")
        #
        #     # Update all test_ids to test.feature
        #     for ti in test_executions[execution_id]["test_infos"]:
        #         ti["test_id"] = "test.feature"
        #
        #     # Copy required mock directories
        #     required_dirs = ["gherkin_files", "log_files", "proofs","output"]
        #     if mock_output_dir.exists():
        #         for dir_name in required_dirs:
        #             src_dir = mock_output_dir / dir_name
        #             dst_dir = opt_dir / dir_name
        #             if src_dir.exists():
        #                 if dst_dir.exists():
        #                     shutil.rmtree(dst_dir)
        #                 shutil.copytree(src_dir, dst_dir)
        #                 logger.info(f"[MOCK] Copied mock directory: {dir_name}")
        #             else:
        #                 FileSystemManager.ensure_dir(dst_dir)
        #                 logger.info(f"[MOCK] Created empty directory: {dir_name}")
        #
        #         # Copy mock test_data
        #         test_data_mock = mock_output_dir / "test_data"
        #         if test_data_mock.exists():
        #             for item in test_data_mock.iterdir():
        #                 dst = test_data_dir / item.name
        #                 if item.is_dir():
        #                     if dst.exists(): shutil.rmtree(dst)
        #                     shutil.copytree(item, dst)
        #                 else:
        #                     shutil.copy2(item, dst)
        #             logger.info(f"[MOCK] Copied mock test data from {test_data_mock}")
        #
        #         # Generate simulated test execution logs
        #         for i in range(5):
        #             logger.info(f"[MOCK TEST] Executing step {i+1}/5 of test scenario")
        #             # Add small delay to make logs appear more realistic
        #             await asyncio.sleep(0.2)
        #
        #         logger.info(f"[MOCK TEST] All steps executed successfully")
        #         logger.info(f"[MOCK TEST] Test execution completed with status: PASSED")
        #         logger.info(f"[MOCK] Mock test execution completed for ID: {execution_id}")
        #
        #         # Set execution status
        #         status = "completed" if result.get("status") == "success" else "failed"
        #         test_executions[execution_id]["status"] = status
        #         test_executions[execution_id]["end_time"] = APIUtils.get_timestamp()
        #         test_executions[execution_id]["result"] = result
        #
        #         # Update database with test result
        #         try:
        #             # Find the db_run_id created earlier
        #             end_time = test_executions[execution_id]["end_time"]
        #
        #             # Query database for the run ID using the test_id
        #             run_records = db.get_runs_by_test_id(test_id)
        #
        #             if run_records and len(run_records) > 0:
        #                 # Update the most recent run record (in case multiple runs exist)
        #                 db_run_id = run_records[-1]['id']
        #                 db.update_run_status(db_run_id, status, end_time)
        #
        #                 # Save result metadata
        #                 if result and isinstance(result, dict):
        #                     # Convert any Path objects to strings
        #                     json_safe_result = path_to_json(result)
        #                     event_data = json.dumps(json_safe_result)
        #                     db.create_event(db_run_id, None, "test_result",
        #                                   f"Test {test_id} {status}", event_data)
        #
        #                 logger.info(f"Updated database record for run ID {db_run_id} with status: {status}")
        #             else:
        #                 logger.warning(f"Could not find database record for test {test_id} to update")
        #         except Exception as db_error:
        #             logger.error(f"Failed to record test completion in database: {db_error}")
        #             # Continue execution even if database update fails
        #
        #         test_executions[execution_id]["result"] = {"status": "mocked", "output_dir": str(run_dir)}
        #         run_dir = OUTPUT_DIR / f"run_{APIUtils.format_run_timestamp()}"
        #         archive_path = await archive_test_results(execution_id, test_id, OPT_DIR)
        #         logger.info("HI IS THIS RUN ? ")
        #         cleanup_result = await cleanup_exec()
        #         logger.info(f"===> Cleanup completed with result: {cleanup_result}")
        #
        #         return {"execution_id": execution_id, "status": "mocked", "start_time": start_time, "output_dir": str(run_dir)}
        #     else:
        #         # No mock output dir found
        #         logger.warning(f"[MOCK] Mock output directory not found at {mock_output_dir}")
        #         test_executions[execution_id]["status"] = "mocked"
        #         test_executions[execution_id]["end_time"] = APIUtils.get_timestamp()
        #         test_executions[execution_id]["result"] = {"status": "mocked"}
        #         return {"execution_id": execution_id, "status": "mocked", "start_time": start_time}
        # More detailed logging before cleanup
        # logger.info(f"===> Starting cleanup before running test execution_id={execution_id}")
        # cleanup_result = await cleanup_exec()
        # logger.info(f"===> Cleanup completed with result: {cleanup_result}")
        # Default response for scheduled tasks
        return {"execution_id": execution_id, "status": "pending", "start_time": start_time, "wsUrl": f"ws://127.0.0.1:{os.getenv('API_PORT', 8000)}/ws/logs/{execution_id}"}
    except HTTPException:
        raise
    except Exception as e:
        # Update execution status to failed in database
        if 'execution_id' in locals():
            test_executions[execution_id]["status"] = "failed"
            test_executions[execution_id]["error"] = str(e)
            try:
                db.update_execution_status(execution_id, "failed")
                logger.error(f"Marked execution as failed in database: {execution_id}")
            except Exception as db_error:
                logger.error(f"Error updating execution status in database: {db_error}")

        raise HTTPException(status_code=500, detail=f"Error running tests from templates: {str(e)}")

@app.get("/executions" ,operation_id = "getExecutionList")
async def get_all_executions(status: Optional[str] = None):
    if(status == ""):
        status = None
    """Get all executions with optional filtering by status.
    
    Args:
        status: Optional filter for execution status (running, pending, completed, failed)
        
    Returns:
        List of execution records
    """
    results = []
    current_time = datetime.now()
    timeout_minutes = 10  # Mark as failed if started more than 10 minutes ago
    running_tests = set()
    
    # First, check if any tests are actually running by checking running processes
    # This helps us identify truly running tests even if their status isn't updated
    try:
        # Use ps command to get list of running testzeus-hercules processes
        cmd = ["ps", "-ef"]
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        output = stdout.decode()
        
        # Find execution IDs in the process list
        for line in output.split('\n'):
            if 'testzeus-hercules' in line:
                # Extract execution ID from command line if possible
                for key in test_executions.keys():
                    if key in line:
                        running_tests.add(key)
                        logger.debug(f"Found running process for execution: {key}")
    except Exception as e:
        logger.error(f"Error checking for running processes: {e}")
    
    # Start by getting in-memory executions
    for exec_id, exec_data in test_executions.items():
        # Skip if it's not an execution record but a test record
        if "test_infos" not in exec_data and "execution_id" not in exec_data:
            continue
            
        current_status = exec_data.get("status", "unknown")
        
        # Override status if test is actually running
        if exec_id in running_tests and current_status in ["pending", "running"]:
            current_status = "running"
            exec_data["status"] = "running"
        
        # If the status is "running" but we have an end_time, something is wrong
        # Fix it by changing the status to "completed"
        if current_status == "running" and exec_data.get("end_time") is not None:
            current_status = "completed"
            exec_data["status"] = "completed"
        
        # If the status is "pending" but it's been a while, check if actually completed
        if current_status == "pending":
            start_time_str = exec_data.get("start_time")
            if start_time_str:
                try:
                    start_time = datetime.fromisoformat(start_time_str)
                    elapsed_minutes = (current_time - start_time).total_seconds() / 60
                    if elapsed_minutes > timeout_minutes:
                        if exec_id not in running_tests:
                            # Check if test is actually completed by looking for result files
                            try:
                                # Correct status based on test runs
                                matching_runs = db.get_runs_by_execution_id(exec_id)
                                if matching_runs:
                                    total_tests = len(matching_runs)
                                    completed_tests = sum(1 for run in matching_runs if run.get("status") in ["completed", "passed", "failed"])
                                    if completed_tests == total_tests:
                                        current_status = "completed"
                                        exec_data["status"] = "completed"
                                        exec_data["end_time"] = datetime.now().isoformat()
                                        db.update_execution_status(exec_id, "completed", exec_data["end_time"])
                                    elif completed_tests > 0:
                                        # Some tests completed but not all
                                        current_status = "running"
                                        exec_data["status"] = "running"
                                    else:
                                        # No tests completed after timeout
                                        current_status = "failed"
                                        exec_data["status"] = "failed"
                                        exec_data["end_time"] = datetime.now().isoformat()
                                        db.update_execution_status(exec_id, "failed", exec_data["end_time"])
                            except Exception as check_error:
                                logger.error(f"Error checking if test is actually completed: {check_error}")
                                # Be conservative, assume failed
                                current_status = "failed"
                                exec_data["status"] = "failed"
                                exec_data["end_time"] = datetime.now().isoformat()
                                db.update_execution_status(exec_id, "failed", exec_data["end_time"])
                except (ValueError, TypeError) as e:
                    logger.error(f"Error parsing start time for execution {exec_id}: {e}")
        
        # If status filter is provided, only include matching executions
        if status is not None and current_status != status:
            continue
            
        # Include basic execution info
        execution = {
            "execution_id": exec_id,
            "status": current_status,
            "start_time": exec_data.get("start_time"),
            "end_time": exec_data.get("end_time", None),
            "completed_tests": exec_data.get("completed_tests", 0),
            "total_tests": len(exec_data.get("test_infos", [])),
            "failed_tests": exec_data.get("failed_tests", 0),
            "source": "memory"
        }
        
        results.append(execution)
    
    # Then get database executions to fill in any missing ones
    try:
        # Add a method to get all executions from database
        db_executions = db.get_all_executions() if hasattr(db, 'get_all_executions') else []
        
        for db_exec in db_executions:
            # Extract fields from database record
            exec_id = db_exec.get("execution_id")
            db_status = db_exec.get("status")
            start_time_str = db_exec.get("start_time")
            
            # Override status if test is actually running
            if exec_id in running_tests and db_status in ["pending", "running"]:
                db_status = "running"
                # Update in database to ensure consistency
                try:
                    db.update_execution_status(exec_id, "running")
                except Exception as e:
                    logger.error(f"Error updating execution status to running: {e}")
            
            # Check if test has been running too long and should be marked as failed
            if db_status in ["running", "pending"] and start_time_str:
                try:
                    start_time = datetime.fromisoformat(start_time_str)
                    elapsed_minutes = (current_time - start_time).total_seconds() / 60
                    
                    if elapsed_minutes > timeout_minutes and exec_id not in running_tests:
                        # Check if test is actually completed by looking for result files
                        try:
                            # Correct status based on test runs
                            matching_runs = db.get_runs_by_execution_id(exec_id)
                            if matching_runs:
                                total_tests = len(matching_runs)
                                completed_tests = sum(1 for run in matching_runs if run.get("status") in ["completed", "passed", "failed"])
                                if completed_tests == total_tests:
                                    db_status = "completed"
                                    db.update_execution_status(exec_id, "completed")
                                elif completed_tests > 0:
                                    # Some tests completed but not all
                                    db_status = "running"
                                else:
                                    # No tests completed after timeout
                                    db_status = "failed"
                                    db.update_execution_status(exec_id, "failed")
                        except Exception as check_error:
                            logger.error(f"Error checking if test is actually completed: {check_error}")
                            # Mark as failed in database
                            logger.warning(f"Execution {exec_id} has been {db_status} for more than {timeout_minutes} minutes. Marking as failed.")
                            db.update_execution_status(exec_id, "failed")
                            db_status = "failed"  # Update status for the result
                except (ValueError, TypeError) as e:
                    logger.error(f"Error parsing start time for execution {exec_id}: {e}")
            
            # Skip if filtered by status
            if status is not None and db_status != status:
                continue
                
            # Check if we already have this execution in memory
            if any(r["execution_id"] == exec_id for r in results):
                continue
                
            # Extract metadata if available
            metadata = db_exec.get("metadata")
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            
            # Add this database execution
            execution = {
                "execution_id": exec_id,
                "status": db_status,
                "start_time": start_time_str,
                "end_time": db_exec.get("end_time"),
                "completed_tests": metadata.get("completed_tests", 0) if metadata else 0,
                "total_tests": metadata.get("total_tests", 0) if metadata else 0,
                "failed_tests": metadata.get("failed_tests", 0) if metadata else 0,
                "source": "database"
            }
            
            results.append(execution)
    except Exception as e:
        logger.error(f"Error retrieving executions from database: {e}")
    
    # Sort results by start_time descending (newest first)
    results.sort(key=lambda x: x.get("start_time", ""), reverse=True)
    
    return results

@router.get("/update-execution-status/{execution_id}")
async def update_execution_status(execution_id: str):
    """Force update of an execution's status based on its test results."""
    
    # Check if execution exists
    if execution_id not in test_executions:
        raise HTTPException(status_code=404, detail=f"Execution ID {execution_id} not found")
    
    # Check database for associated test runs
    matching_runs = db.get_runs_by_execution_id(execution_id)
    
    if not matching_runs:
        return {"message": f"No test runs found for execution {execution_id}"}
    
    # Calculate status based on test runs
    total_tests = len(matching_runs)
    completed_tests = 0
    failed_tests = 0
    
    for run in matching_runs:
        status = run.get("status")
        if status in ["completed", "failed", "error"]:
            completed_tests += 1
            if status in ["failed", "error"]:
                failed_tests += 1
    
    # Determine execution status
    if completed_tests == total_tests:
        execution_status = "failed" if failed_tests > 0 else "completed"
        end_time = datetime.now().isoformat()
        
        # Update memory
        test_executions[execution_id]["status"] = execution_status
        test_executions[execution_id]["end_time"] = end_time
        test_executions[execution_id]["completed_tests"] = completed_tests
        test_executions[execution_id]["failed_tests"] = failed_tests
        
        # Update database
        db.update_execution_status(execution_id, execution_status, end_time)
        
        return {
            "message": f"Execution status updated to {execution_status}",
            "execution_id": execution_id,
            "status": execution_status,
            "completed_tests": completed_tests,
            "total_tests": total_tests,
            "failed_tests": failed_tests
        }
    else:
        current_status = test_executions[execution_id].get("status", "running")
        return {
            "message": f"Execution still in progress: {completed_tests}/{total_tests} tests completed",
            "execution_id": execution_id,
            "status": current_status,
            "completed_tests": completed_tests,
            "total_tests": total_tests
        }

def path_to_json(obj):
    """Convert Path objects to strings for JSON serialization.
    
    Args:
        obj: Object to convert
        
    Returns:
        JSON-serializable object
    """
    if isinstance(obj, Path):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: path_to_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [path_to_json(item) for item in obj]
    else:
        return obj

async def process_xml_directly(execution_id: str, test_id: str) -> Tuple[int, int]:
    """Process XML test results directly without using external process_xml_results module.
    
    Args:
        execution_id: ID of the execution
        test_id: ID of the test (optional)
        
    Returns:
        Tuple of (processed_count, error_count)
    """
    from pathlib import Path
    from src.utils.database import db
    from src.utils.paths import get_data_dir
    
    # Track statistics
    processed_count = 0
    error_count = 0
    
    try:
        # Get data directory
        data_dir = get_data_dir()
        
        # Check both temporary and permanent storage locations
        exec_dir = data_dir / "manager" / "exec" / f"run_{execution_id}"
        perm_dir = data_dir / "manager" / "perm" / "ExecutionResultHistory" / f"run_{execution_id}"
        
        # Process directory if it exists
        if perm_dir.exists():
            logger.info(f"Found execution in permanent storage: {perm_dir}")
            target_dir = perm_dir
        elif exec_dir.exists():
            logger.info(f"Found execution in temporary storage: {exec_dir}")
            target_dir = exec_dir
        else:
            logger.warning(f"No execution directory found for ID: {execution_id}")
            return 0, 0
        
        # If test_id specified, look for that specific test
        if test_id:
            test_output_dir = target_dir / "opt" / "tests" / test_id / "output"
            if not test_output_dir.exists():
                logger.warning(f"No output directory found for test: {test_id}")
                return 0, 0
                
            # Look for XML files
            test_dirs = [(test_id, test_output_dir)]
        else:
            # Look for all tests in the execution directory
            tests_dir = target_dir / "opt" / "tests"
            if not tests_dir.exists():
                logger.warning(f"No tests directory found in execution: {execution_id}")
                return 0, 0
                
            test_dirs = []
            for test_dir in tests_dir.iterdir():
                if test_dir.is_dir():
                    output_dir = test_dir / "output"
                    if output_dir.exists():
                        test_dirs.append((test_dir.name, output_dir))
        
        # Process each test directory
        for test_id, output_dir in test_dirs:
            logger.info(f"Processing XML for test: {test_id}")
            
            # Find run directories in output
            run_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("run_")]
            if not run_dirs:
                logger.info(f"No run directories found for test: {test_id}")
                continue
                
            # Sort by modified time (newest first)
            run_dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            for run_dir in run_dirs:
                # Look for XML files in this run directory
                xml_files = list(run_dir.glob("*.xml"))
                if not xml_files:
                    logger.info(f"No XML files found in run directory: {run_dir}")
                    continue
                    
                # Sort by modified time (newest first)
                xml_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                
                # Process the newest XML file
                xml_file = xml_files[0]
                logger.info(f"Found XML result file: {xml_file}")
                
                # Store XML result in database
                try:
                    xml_id = db.store_xml_test_results(
                        execution_id=execution_id,
                        test_id=test_id,
                        xml_file_path=str(xml_file)
                    )
                    
                    if xml_id:
                        logger.info(f"Stored XML result with ID: {xml_id}")
                        processed_count += 1
                    else:
                        logger.error(f"Failed to store XML result: {xml_file}")
                        error_count += 1
                except Exception as e:
                    logger.error(f"Error processing XML file {xml_file}: {e}")
                    error_count += 1
                
                # Only process the newest XML file for each test
                break
        
        return processed_count, error_count
    except Exception as e:
        logger.error(f"Error during direct XML processing: {e}")
        return 0, 1

@router.post("/executions/{execution_id}/test/{test_id}/status", response_model=dict)
async def update_test_status(execution_id: str, test_id: str, status: str, message: Optional[str] = "", steps: Optional[List[Dict[str, Any]]] = None):
    """Update the status of a specific test run.
    
    Args:
        execution_id: ID of the test execution
        test_id: ID of the test
        status: New status (e.g., "completed", "failed", "aborted")
        message: Optional message with additional information
        steps: Optional list of test steps with status updates
    
    Returns:
        Updated test status
    """
    logger.info(f"Updating test status for execution: {execution_id}, test: {test_id}, status: {status}")
    
    try:
        # Always update local test_executions entry and database
        db.update_run_status(test_id=test_id, status=status)
        
        # If the test has completed (successfully or with failure), look for XML results
        if status in ["completed", "failed"]:
            try:
                # Try to find and process XML results directly
                logger.info(f"Test {test_id} {status}, processing XML results")
                processed_count, error_count = await process_xml_directly(execution_id, test_id)
                
                if processed_count > 0:
                    logger.info(f"Automatically processed {processed_count} XML files for execution {execution_id}, test {test_id}")
                else:
                    logger.warning(f"No XML results found for test {test_id} in execution {execution_id}")
                    
            except Exception as e:
                logger.error(f"Error processing XML results during status update: {e}")
                # Continue with the status update even if XML processing fails
        
        # Update steps if provided
        if steps:
            for step in steps:
                step_id = step.get("id")
                step_status = step.get("status")
                step_message = step.get("message", "")
                
                if step_id and step_status:
                    db.update_step_status(
                        test_id=test_id,
                        step_id=step_id,
                        status=step_status,
                        message=step_message
                    )
        
        # Update in-memory state if available
        if execution_id in test_executions:
            execution = test_executions[execution_id]
            if test_id in execution.tests:
                test = execution.tests[test_id]
                test.status = status
                test.message = message
                
                if steps:
                    for step_update in steps:
                        step_id = step_update.get("id")
                        if step_id in test.steps:
                            step = test.steps[step_id]
                            step.status = step_update.get("status", step.status)
                            step.message = step_update.get("message", step.message)
        
        return {
            "execution_id": execution_id,
            "test_id": test_id,
            "status": status,
            "message": message
        }
    except Exception as e:
        logger.error(f"Error updating test status: {e}")
        return {
            "execution_id": execution_id,
            "test_id": test_id,
            "error": str(e)
        }

@router.post("/executions/{execution_id}/process-xml", response_model=dict)
async def process_execution_xml(execution_id: str):
    """Process XML test results for an execution and store them in the database.
    
    Args:
        execution_id: ID of the execution
        
    Returns:
        Processing results
    """
    logger.info(f"Processing XML results for execution: {execution_id}")
    
    try:
        # Process XML results directly
        processed_count, error_count = await process_xml_directly(execution_id, None)
        
        # Return results
        return {
            "execution_id": execution_id,
            "processed_count": processed_count,
            "error_count": error_count,
            "message": f"Processed {processed_count} XML files with {error_count} errors"
        }
    except Exception as e:
        logger.error(f"Error processing XML results: {e}")
        return {
            "execution_id": execution_id,
            "error": str(e)
        }

@router.post("/process-xml", response_model=dict)
async def process_all_xml_results(days: Optional[int] = 7):
    """Process XML test results for all executions.
    
    Args:
        days: Number of days to look back for results (default: 7)
        
    Returns:
        Processing result
    """
    logger.info(f"Triggering XML processing for all executions in the last {days} days")
    
    try:
        # Import the processing function
        from src.tools.process_xml_results import process_xml_results
        
        # Process XML results
        processed, errors = process_xml_results(days=days)
        
        # Return the result
        return {
            "days": days,
            "processed_files": processed,
            "errors": errors,
            "status": "success" if errors == 0 else "partial_success" if processed > 0 else "failed"
        }
    except Exception as e:
        logger.error(f"Error processing XML results: {e}")
        return {
            "days": days,
            "status": "error",
            "error": str(e)
        }

@app.get("/test-definition-data", operation_id="getAllTestDefinitionData")
async def get_all_test_definition_data():
    """
      Returns complete content of all feature files and test data files from the library.

      - Scans `data/manager/lib/features/` for Gherkin feature files
      - Scans `data/manager/lib/test_data/` for test data files
      - Provides file paths (relative and absolute) and full content

      Use this to discover available templates before executing tests with `runningATemplate`.

      Example response structure:
      ```json
      {
        "feature_data_list": [
          {
            "path": "basic/login.feature",
            "content": "Feature: Login Test\n...",
            "is_binary": false
          }
        ],
        "test_data_list": [
          {
            "path": "credentials.txt",
            "content": "username=admin\npassword=secret",
            "is_binary": false
          }
        ]
      }
      ```
    """
    logger.info("Getting all test definition data")
    
    # Get configured directories using the Config utility
    dirs = Config.get_data_directories()
    feature_dir = dirs["library"]
    test_data_dir = dirs["test_data_library"]
    
    logger.info(f"Using feature directory: {feature_dir}")
    logger.info(f"Using test data directory: {test_data_dir}")
    
    # Result containers
    feature_data_list = []
    test_data_list = []
    
    # Function to recursively read files from a directory
    def read_files_recursively(base_dir, relative_to, result_list):
        if not base_dir.exists() or not base_dir.is_dir():
            logger.warning(f"Directory {base_dir} does not exist or is not a directory")
            return
            
        for item in base_dir.glob('**/*'):
            if item.is_file():
                try:
                    # Calculate the relative path
                    rel_path = str(item.relative_to(relative_to))
                    
                    # For text files, try to read content with various encodings
                    # For binary files, skip or handle separately
                    file_ext = item.suffix.lower()
                    is_binary = file_ext in ['.bin', '.exe', '.dll', '.so', '.pyc', '.jpg', '.jpeg', '.png', '.gif']
                    
                    if is_binary:
                        # For binary files, just note it's binary content
                        content = "[Binary file - content not included]"
                    else:
                        # Try UTF-8 first, then fallback to latin-1 which accepts any byte sequence
                        try:
                            with open(item, 'r', encoding='utf-8') as f:
                                content = f.read()
                        except UnicodeDecodeError:
                            try:
                                with open(item, 'r', encoding='latin-1') as f:
                                    content = f.read()
                            except Exception as enc_error:
                                logger.error(f"Error reading file with latin-1 encoding: {item}: {enc_error}")
                                content = f"[Error reading file content: {str(enc_error)}]"
                    
                    # Add to result list
                    result_list.append({
                        "path": rel_path,
                        "full_file_path": str(item),
                        "content": content,
                        "is_binary": is_binary
                    })
                except Exception as e:
                    logger.error(f"Error reading file {item}: {e}")
    
    # Read feature files
    read_files_recursively(feature_dir, feature_dir, feature_data_list)
    
    # Read test data files
    read_files_recursively(test_data_dir, test_data_dir, test_data_list)
    
    # Generate a unique operation ID
    operation_id = str(uuid.uuid4())
    
    return {
        "feature_data_list": feature_data_list,
        "test_data_list": test_data_list,
        "operation_id": operation_id
    }

@app.post("/bulk-upload-files1", operation_id="bulkUploadTestDefinitionFiles")
async def bulk_upload_files(request: HFileRequest, background_tasks: BackgroundTasks):
    """
    Upload multiple files in bulk to the test definition directories.
    
    This endpoint accepts an array of file objects with the following structure:
    ```json
     [
            {
            "path": "relative path within the appropriate directory",
            "type": "feature|test_data",
            "content": "The full text content of the file"
            }
        ]
    ```
    
    Features are saved to `data/manager/lib/features/` directory.
    Test data is saved to `data/manager/lib/test_data/` directory.
    
    Returns a list of results for each file upload operation.
    """
    files = request.files
    logger.info(f"Bulk uploading {len(files)} files")
    
    # Get configured directories using the Config utility
    dirs = Config.get_data_directories()
    feature_dir = dirs["library"]
    test_data_dir = dirs["test_data_library"]
    
    logger.info(f"Using feature directory: {feature_dir}")
    logger.info(f"Using test data directory: {test_data_dir}")
    
    results = []
    
    for file_data in files:
        try:
            file_path = file_data.path
            file_type = file_data.type
            file_content = file_data.content

            
            # Validate input parameters
            if not file_path:
                results.append({
                    "path": file_path,
                    "status": "error", 
                    "message": "Missing required 'path' parameter"
                })
                continue
                
            if not file_type:
                results.append({
                    "path": file_path,
                    "status": "error", 
                    "message": "Missing required 'type' parameter"
                })
                continue
                
            if file_content is None:
                results.append({
                    "path": file_path,
                    "status": "error", 
                    "message": "Missing required 'content' parameter"
                })
                continue
                
            # Sanitize path (remove any leading slashes or parent dir references)
            sanitized_path = file_path.lstrip('/').replace('../', '').replace('..\\', '')
            
            # Determine target directory based on file type
            if file_type.lower() == "feature":
                target_dir = feature_dir
            elif file_type.lower() == "test_data":
                target_dir = test_data_dir
            else:
                results.append({
                    "path": file_path,
                    "status": "error",
                    "message": f"Invalid file type: {file_type}. Must be 'feature' or 'test_data'"
                })
                continue
                
            # Create full target path
            target_path = target_dir / sanitized_path
            
            # Ensure parent directory exists
            os.makedirs(target_path.parent, exist_ok=True)
            
            # Write file content
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(file_content)
                
            results.append({
                "path": file_path,
                "status": "success",
                "message": f"File successfully written to {target_path}"
            })
            
            logger.info(f"Successfully wrote file to {target_path}")
            
        except Exception as e:
            # logger.error(f"Error writing file {file_data.get('path', 'unknown')}: {str(e)}")
            results.append({
                "path":  "unknown",
                "status": "error",
                "message": f"Error: {str(e)}"
            })
    
    return {
        "operation_id": str(uuid.uuid4()),
        "total_files": len(files),
        "successful": sum(1 for r in results if r.get("status") == "success"),
        "failed": sum(1 for r in results if r.get("status") == "error"),
        "results": results
    }

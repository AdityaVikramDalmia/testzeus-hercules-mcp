#!/usr/bin/env python
"""
Process XML Results Script

This script scans the execution directories for XML test result files,
and stores them in the SQLite database for reporting and analysis.

Usage:
    python process_xml_results.py [--execution_id EXECUTION_ID] [--days DAYS]
    
Options:
    --execution_id  Process results for a specific execution ID only
    --days          Process results from the last N days (default: 7)
"""

import os
import sys
import argparse
import logging
import datetime
from pathlib import Path
from datetime import datetime, timedelta
import glob
import re

# Add the project root to the Python path
script_dir = Path(__file__).parent
project_root = script_dir.parent.parent
sys.path.insert(0, str(project_root))

# Import database tools
from src.utils.database import db
from src.utils.paths import get_data_dir

# Create a standalone logger that won't interfere with the global logger
xml_logger = logging.getLogger("xml_processor")

def process_xml_results(execution_id=None, days=7):
    """Process XML test results and store them in the database.
    
    Args:
        execution_id: Optional execution ID to process results for
        days: Number of days to look back for results
    
    Returns:
        Tuple of (processed_count, error_count)
    """
    from src.utils.logger import logger
    
    logger.info(f"Starting XML results processing: execution_id={execution_id}, days={days}")
    
    # Get data directory
    data_dir = get_data_dir()
    executions_dir = data_dir / "manager" / "exec"
    perm_storage_dir = data_dir / "manager" / "perm" / "ExecutionResultHistory"
    
    # Track statistics
    processed_count = 0
    error_count = 0
    
    # First check permanent storage - it takes precedence over temporary storage
    if execution_id:
        # Process a specific execution
        perm_paths = []
        if perm_storage_dir.exists():
            perm_paths = list(perm_storage_dir.glob(f"run_{execution_id}*"))
        
        if perm_paths:
            logger.info(f"Found execution in permanent storage: {execution_id}")
            p_count, e_count = process_execution_paths(perm_paths, execution_id, days, is_permanent=True)
            processed_count += p_count
            error_count += e_count
        
        # If not in permanent storage, check temporary storage
        if not executions_dir.exists():
            if processed_count == 0 and error_count == 0:
                logger.error(f"Executions directory not found: {executions_dir}")
                return 0, 1
        else:
            exec_paths = list(executions_dir.glob(f"run_{execution_id}*"))
            if exec_paths:
                logger.info(f"Found execution in temporary storage: {execution_id}")
                t_count, t_error = process_execution_paths(exec_paths, execution_id, days)
                processed_count += t_count
                error_count += t_error
            elif processed_count == 0:
                logger.warning(f"No execution directory found for ID: {execution_id}")
    else:
        # Process all executions within the date range
        # First check permanent storage
        if perm_storage_dir.exists():
            perm_paths = [p for p in perm_storage_dir.iterdir() if p.is_dir() and p.name.startswith("run_")]
            if perm_paths:
                logger.info(f"Found {len(perm_paths)} permanent execution directories to process")
                perm_processed, perm_errors = process_execution_paths(perm_paths, execution_id, days, is_permanent=True)
                processed_count += perm_processed
                error_count += perm_errors
        
        # Then check temporary storage
        if executions_dir.exists():
            exec_paths = [p for p in executions_dir.iterdir() if p.is_dir() and p.name.startswith("run_")]
            if exec_paths:
                logger.info(f"Found {len(exec_paths)} temporary execution directories to process")
                temp_processed, temp_errors = process_execution_paths(exec_paths, execution_id, days)
                processed_count += temp_processed
                error_count += temp_errors
        else:
            logger.warning(f"Executions directory not found: {executions_dir}")
    
    logger.info(f"XML processing complete. Processed: {processed_count}, Errors: {error_count}")
    return processed_count, error_count

def process_execution_paths(exec_paths, execution_id=None, days=7, is_permanent=False):
    """Process a list of execution paths to extract and store XML results.
    
    Args:
        exec_paths: List of execution directory paths
        execution_id: Optional execution ID filter
        days: Number of days to look back for results
        is_permanent: Whether these paths are from permanent storage
        
    Returns:
        Tuple of (processed_count, error_count)
    """
    from src.utils.logger import logger
    
    # Calculate cutoff date
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Track statistics
    processed_count = 0
    error_count = 0
    
    for exec_path in exec_paths:
        try:
            # Extract execution ID from directory name
            if execution_id:
                current_exec_id = execution_id
            else:
                match = re.search(r"run_([a-f0-9-]+)", exec_path.name)
                if match:
                    current_exec_id = match.group(1)
                else:
                    logger.warning(f"Could not extract execution ID from: {exec_path.name}")
                    continue
            
            # Check directory modification time against cutoff date if no specific execution_id
            if not execution_id:
                dir_mtime = datetime.fromtimestamp(exec_path.stat().st_mtime)
                if dir_mtime < cutoff_date:
                    logger.debug(f"Skipping older directory: {exec_path} (modified: {dir_mtime})")
                    continue
            
            logger.info(f"Processing execution: {current_exec_id} ({exec_path})")
            
            # Find XML files in test output directories
            if is_permanent:
                # In permanent storage, look for preserved structure
                output_dirs = list(exec_path.glob("opt/tests/*/output"))
            else:
                # Normal structure in temporary storage
                output_dirs = list(exec_path.glob("opt/tests/*/output"))
                
            for output_dir in output_dirs:
                # Extract test ID from path
                test_match = re.search(r"tests/([^/]+)/output", str(output_dir))
                if not test_match:
                    logger.warning(f"Could not extract test ID from: {output_dir}")
                    continue
                
                test_id = test_match.group(1)
                logger.info(f"Processing test: {test_id}")
                
                # Find run directories within the output directory
                run_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("run_")]
                
                # Sort by modified time (newest first)
                run_dirs = sorted(run_dirs, key=lambda x: x.stat().st_mtime, reverse=True)
                
                for run_dir in run_dirs:
                    # Look for XML files in this run directory
                    xml_files = list(run_dir.glob("*.xml"))
                    
                    if xml_files:
                        # Sort by modified time (newest first)
                        xml_files = sorted(xml_files, key=lambda x: x.stat().st_mtime, reverse=True)
                        
                        # Process the newest XML file
                        xml_file = xml_files[0]
                        logger.info(f"Found XML result file: {xml_file}")
                        
                        # Check if this XML file has already been processed
                        existing_results = db.get_xml_test_results(
                            execution_id=current_exec_id, 
                            test_id=test_id
                        )
                        
                        # Only check matching XML path if we're processing a permanent storage XML
                        # For temporary files, always allow reprocessing since paths might need transformation
                        if is_permanent and existing_results and any(r.get("xml_file_path") == str(xml_file) for r in existing_results):
                            logger.info(f"XML file already processed: {xml_file}")
                            continue
                        
                        # Store XML result in database
                        xml_id = db.store_xml_test_results(
                            execution_id=current_exec_id,
                            test_id=test_id,
                            xml_file_path=str(xml_file)
                        )
                        
                        if xml_id:
                            logger.info(f"Stored XML result with ID: {xml_id}")
                            processed_count += 1
                        else:
                            logger.error(f"Failed to store XML result: {xml_file}")
                            error_count += 1
                        
                        # Only process the newest XML file for each test
                        break
        except Exception as e:
            logger.error(f"Error processing execution directory {exec_path}: {e}")
            error_count += 1
    
    return processed_count, error_count

def main():
    """Main entry point when run as a script."""
    # Configure logging for the command-line script
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    
    parser = argparse.ArgumentParser(description='Process XML test results and store them in the database.')
    parser.add_argument('--execution_id', help='Process results for a specific execution ID only')
    parser.add_argument('--days', type=int, default=7, help='Process results from the last N days (default: 7)')
    
    args = parser.parse_args()
    
    processed_count, error_count = process_xml_results(args.execution_id, args.days)
    
    print(f"XML processing complete. Processed: {processed_count}, Errors: {error_count}")
    
    # Return appropriate exit code
    if error_count > 0 and processed_count == 0:
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main()) 
import os
import sqlite3
import json
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Union, Tuple
from src.utils.logger import logger

class Database:
    """SQLite database for tracking execution runs."""
    
    def __init__(self, db_path: Optional[str] = None):
        """Initialize the database connection.
        
        Args:
            db_path: Path to the SQLite database file. If None, uses default path in data directory.
        """
        # Initialize logger
        self.logger = logger
        
        if db_path is None:
            # Use default path in data directory
            from src.utils.paths import get_data_dir
            data_dir = get_data_dir()
            db_path = str(data_dir / "execution_runs.db")
        
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._create_tables()
        # Set pragma to ensure immediate disk writes
        self.conn.execute("PRAGMA synchronous = FULL")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.commit()
        logger.info(f"Database initialized at {self.db_path} with automatic flush enabled")
    
    def _connect(self) -> None:
        """Connect to the SQLite database."""
        try:
            self.conn = sqlite3.connect(self.db_path)
            # Enable foreign keys
            self.conn.execute("PRAGMA foreign_keys = ON")
            # Configure connection to return rows as dictionaries
            self.conn.row_factory = sqlite3.Row
            logger.debug(f"Connected to database at {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Database connection error: {e}")
            raise
    
    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        try:
            cursor = self.conn.cursor()
            
            # Create runs table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id TEXT NOT NULL,
                start_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_time TIMESTAMP,
                status TEXT DEFAULT 'running',
                browser_type TEXT,
                headless BOOLEAN,
                environment TEXT,
                metadata TEXT,
                UNIQUE(test_id, start_time)
            )
            ''')
            
            # Create steps table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                step_index INTEGER NOT NULL,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                start_time TIMESTAMP,
                end_time TIMESTAMP,
                screenshot_path TEXT,
                error_message TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
                UNIQUE(run_id, step_index)
            )
            ''')
            
            # Create events table for logging events during test execution
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                step_id INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                data TEXT,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE CASCADE,
                FOREIGN KEY (step_id) REFERENCES steps(id) ON DELETE CASCADE
            )
            ''')
            
            # Create executions table
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id TEXT NOT NULL,
                status TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                metadata TEXT,
                UNIQUE(execution_id)
            )
            ''')
            
            # Create test_xml_results table for storing detailed XML test results
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS test_xml_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER,
                execution_id TEXT NOT NULL,
                test_id TEXT NOT NULL,
                testsuite_name TEXT,
                tests_count INTEGER,
                errors_count INTEGER,
                failures_count INTEGER, 
                skipped_count INTEGER,
                time REAL,
                timestamp TEXT,
                test_name TEXT,
                test_classname TEXT,
                test_time REAL,
                system_out TEXT,
                property_terminate TEXT,
                property_feature_file TEXT,
                property_output_file TEXT,
                property_proofs_video TEXT,
                property_proofs_base_folder TEXT,
                property_proofs_screenshot TEXT,
                property_network_logs TEXT,
                property_agents_logs TEXT, 
                property_planner_thoughts TEXT,
                property_plan TEXT,
                property_next_step TEXT,
                property_terminate_flag TEXT,
                property_target_helper TEXT,
                final_response TEXT,
                total_execution_cost REAL,
                total_token_used INTEGER,
                xml_file_path TEXT,
                test_passed BOOLEAN,
                FOREIGN KEY (run_id) REFERENCES runs(id) ON DELETE SET NULL,
                UNIQUE(execution_id, test_id)
            )
            ''')
            
            self.conn.commit()
            logger.debug("Database tables created successfully")
        except sqlite3.Error as e:
            logger.error(f"Error creating database tables: {e}")
            raise
    
    def create_run(self, test_id: str, browser_type: str = "chromium", 
                  headless: bool = True, environment: str = "default",
                  metadata: Optional[Union[Dict[str, Any], str]] = None, 
                  status: str = "running",
                  start_time: Optional[str] = None,
                  end_time: Optional[str] = None) -> int:
        """Create a new test run record.
        
        Args:
            test_id: ID or path of the test being executed
            browser_type: Type of browser used for the test
            headless: Whether the browser is running in headless mode
            environment: Environment name (e.g., "production", "staging")
            metadata: Additional metadata as a dictionary or JSON string
            status: Initial status of the run (default: "running")
            start_time: Start time of the run (ISO format). If None, uses current time.
            end_time: End time of the run (ISO format). Only set if status is not "running".
            
        Returns:
            The ID of the created run
        """
        try:
            # Ensure start time is set
            if start_time is None:
                start_time = datetime.datetime.now().isoformat()
                
            # Convert metadata to JSON string if needed
            metadata_json = metadata
            if isinstance(metadata, dict):
                metadata_json = json.dumps(metadata)
            elif metadata is None:
                metadata_json = "{}"

            # Prepare SQL based on whether end_time is provided
            if end_time is not None:
                cursor = self.conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO runs (test_id, browser_type, headless, environment, metadata, status, start_time, end_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        test_id,
                        browser_type,
                        headless,
                        environment,
                        metadata_json,
                        status,
                        start_time,
                        end_time
                    )
                )
            else:
                cursor = self.conn.cursor()
                cursor.execute(
                    '''
                    INSERT INTO runs (test_id, browser_type, headless, environment, metadata, status, start_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''',
                    (
                        test_id,
                        browser_type,
                        headless,
                        environment,
                        metadata_json,
                        status,
                        start_time
                    )
                )
                
            self.conn.commit()
            self.flush()  # Ensure data is written to disk
            run_id = cursor.lastrowid
            logger.debug(f"Created new run with ID {run_id} for test {test_id}")
            return run_id
        except sqlite3.Error as e:
            logger.error(f"Error creating run record: {e}")
            self.conn.rollback()
            raise
    
    def update_run_status(self, run_id: int, status: str, end_time: Optional[str] = None) -> None:
        """Update the status of a test run.
        
        Args:
            run_id: ID of the run to update
            status: New status (e.g., "completed", "failed", "aborted")
            end_time: End time of the run (ISO format). If None, uses current time.
        """
        if end_time is None:
            end_time = datetime.datetime.now().isoformat()
            
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                '''
                UPDATE runs 
                SET status = ?, end_time = ? 
                WHERE id = ?
                ''',
                (status, end_time, run_id)
            )
            self.conn.commit()
            logger.debug(f"Updated run {run_id} status to {status}")
        except sqlite3.Error as e:
            logger.error(f"Error updating run status: {e}")
            self.conn.rollback()
            raise
    
    def create_step(self, run_id: int, step_index: int, description: str) -> int:
        """Create a new test step record.
        
        Args:
            run_id: ID of the run this step belongs to
            step_index: Index of the step in the test
            description: Description of the step
            
        Returns:
            The ID of the created step
        """
        try:
            start_time = datetime.datetime.now().isoformat()
            cursor = self.conn.cursor()
            cursor.execute(
                '''
                INSERT INTO steps (run_id, step_index, description, status, start_time)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (run_id, step_index, description, "running", start_time)
            )
            self.conn.commit()
            step_id = cursor.lastrowid
            logger.debug(f"Created step {step_id} for run {run_id}")
            return step_id
        except sqlite3.Error as e:
            logger.error(f"Error creating step record: {e}")
            self.conn.rollback()
            raise
    
    def update_step_status(self, step_id: int, status: str, screenshot_path: Optional[str] = None, error_message: Optional[str] = None) -> None:
        """Update the status of a test step.
        
        Args:
            step_id: ID of the step to update
            status: New status (e.g., "completed", "failed", "skipped")
            screenshot_path: Path to the screenshot taken during step execution
            error_message: Error message if the step failed
        """
        try:
            end_time = datetime.datetime.now().isoformat()
            cursor = self.conn.cursor()
            cursor.execute(
                '''
                UPDATE steps
                SET status = ?, end_time = ?, screenshot_path = ?, error_message = ?
                WHERE id = ?
                ''',
                (status, end_time, screenshot_path, error_message, step_id)
            )
            self.conn.commit()
            logger.debug(f"Updated step {step_id} status to {status}")
        except sqlite3.Error as e:
            logger.error(f"Error updating step status: {e}")
            self.conn.rollback()
            raise
            
    def get_all_runs(self) -> List[Dict[str, Any]]:
        """Get all test runs from the database.
        
        Returns:
            List of all test run records as dictionaries
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM runs ORDER BY start_time DESC')
            rows = cursor.fetchall()
            runs = []
            for row in rows:
                run_data = dict(row)
                # Parse JSON fields
                if run_data.get("metadata") and isinstance(run_data["metadata"], str):
                    try:
                        run_data["metadata"] = json.loads(run_data["metadata"])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse metadata JSON for run {run_data.get('id')}, converting to dictionary")
                        # Convert to a simple dict to avoid get() errors
                        run_data["metadata"] = {"raw_value": run_data["metadata"]}
                runs.append(run_data)
            return runs
        except sqlite3.Error as e:
            logger.error(f"Error retrieving all runs: {e}")
            return []
            
    def get_runs_by_test_id(self, test_id: str) -> List[Dict[str, Any]]:
        """Get all runs for a specific test ID.
        
        Args:
            test_id: ID of the test to retrieve runs for
            
        Returns:
            List of test run records as dictionaries
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                '''
                SELECT * FROM runs
                WHERE test_id = ?
                ORDER BY start_time DESC
                ''',
                (test_id,)
            )
            rows = cursor.fetchall()
            runs = []
            for row in rows:
                run_data = dict(row)
                # Parse JSON fields
                if run_data.get("metadata") and isinstance(run_data["metadata"], str):
                    try:
                        run_data["metadata"] = json.loads(run_data["metadata"])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse metadata JSON for run {run_data.get('id')}, converting to dictionary")
                        # Convert to a simple dict to avoid get() errors
                        run_data["metadata"] = {"raw_value": run_data["metadata"]}
                runs.append(run_data)
            return runs
        except sqlite3.Error as e:
            logger.error(f"Error retrieving runs by test ID: {e}")
            return []
            
    def get_steps_by_run_id(self, run_id: int) -> List[Dict[str, Any]]:
        """Get all steps for a specific test run.
        
        Args:
            run_id: ID of the run to retrieve steps for
            
        Returns:
            List of step records as dictionaries
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                '''
                SELECT * FROM steps
                WHERE run_id = ?
                ORDER BY step_index
                ''',
                (run_id,)
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Error retrieving steps by run ID: {e}")
            return []
            
    def get_events_by_run_id(self, run_id: int, step_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all events for a specific test run or step.
        
        Args:
            run_id: ID of the run to retrieve events for
            step_id: Optional ID of the step to filter events by
            
        Returns:
            List of event records as dictionaries
        """
        try:
            cursor = self.conn.cursor()
            if step_id is not None:
                cursor.execute(
                    '''
                    SELECT * FROM events
                    WHERE run_id = ? AND step_id = ?
                    ORDER BY timestamp
                    ''',
                    (run_id, step_id)
                )
            else:
                cursor.execute(
                    '''
                    SELECT * FROM events
                    WHERE run_id = ?
                    ORDER BY timestamp
                    ''',
                    (run_id,)
                )
            rows = cursor.fetchall()
            events = []
            for row in rows:
                event_data = dict(row)
                # Parse JSON fields
                if event_data.get("data") and isinstance(event_data["data"], str):
                    try:
                        event_data["data"] = json.loads(event_data["data"])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse data JSON for event {event_data.get('id')}, converting to dictionary")
                        # Convert to a simple dict to avoid get() errors
                        event_data["data"] = {"raw_value": event_data["data"]}
                events.append(event_data)
            return events
        except sqlite3.Error as e:
            logger.error(f"Error retrieving events: {e}")
            return []
            
    def create_event(self, run_id: int, step_id: Optional[int], event_type: str, message: str, 
                 data: Optional[Union[Dict[str, Any], str]] = None) -> int:
        """Log an event during test execution.
        
        Args:
            run_id: ID of the run this event belongs to
            step_id: ID of the step this event belongs to (optional)
            event_type: Type of event (e.g., "info", "warning", "error", "test_result")
            message: Event message
            data: Additional data as a dictionary or JSON string
            
        Returns:
            The ID of the created event
        """
        try:
            # Handle data that might be a string or a dictionary
            data_json = None
            if data is not None:
                if isinstance(data, str):
                    # If it's already a string, try to validate it's proper JSON
                    try:
                        # Verify it's valid JSON by parsing it
                        json.loads(data)
                        data_json = data  # It's already a valid JSON string
                    except json.JSONDecodeError:
                        # If it's not valid JSON, store it as a simple string value
                        data_json = json.dumps({"value": data})
                        logger.warning(f"Invalid JSON event data converted to simple value: {data}")
                else:
                    # If it's a dictionary or other object, convert to JSON string
                    data_json = json.dumps(data)
            
            cursor = self.conn.cursor()
            cursor.execute(
                '''
                INSERT INTO events (run_id, step_id, event_type, message, data)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (
                    run_id,
                    step_id,
                    event_type,
                    message,
                    data_json
                )
            )
            self.conn.commit()
            event_id = cursor.lastrowid
            logger.debug(f"Logged event {event_id} for run {run_id}")
            return event_id
        except sqlite3.Error as e:
            logger.error(f"Error logging event: {e}")
            self.conn.rollback()
            raise
            
    def create_execution(self, execution_id, status="pending", metadata=None):
        """Create a new execution record to track multiple tests.
        
        Args:
            execution_id: The unique execution ID
            status: Initial status (pending, running, completed, failed)
            metadata: Optional metadata for the execution
            
        Returns:
            int: The ID of the created execution record
        """
        try:
            # Convert metadata to JSON string if provided
            metadata_json = json.dumps(metadata) if metadata else None
            
            # Insert the execution record
            query = """
                INSERT INTO executions (
                    execution_id, status, start_time, metadata
                ) VALUES (?, ?, datetime('now'), ?)
            """
            
            cursor = self.conn.cursor()
            cursor.execute(query, (execution_id, status, metadata_json))
            self.conn.commit()
            
            # Return the ID of the created execution
            return cursor.lastrowid
        except Exception as e:
            self.logger.error(f"Error creating execution record: {e}")
            return None
    
    def get_execution(self, execution_id):
        """Get an execution record by its execution_id."""
        try:
            query = "SELECT * FROM executions WHERE execution_id = ?"
            cursor = self.conn.cursor()
            cursor.execute(query, (execution_id,))
            row = cursor.fetchone()
            
            if row:
                return dict(row)
            return None
        except Exception as e:
            self.logger.error(f"Error retrieving execution: {e}")
            return None
    
    def update_execution_status(self, execution_id, status, end_time=None):
        """Update the status of an execution.
        
        Args:
            execution_id: The unique execution ID
            status: New status (e.g., "running", "completed", "failed")
            end_time: End time of the execution (ISO format). If None, uses current time.
        """
        try:
            if end_time is None:
                end_time = datetime.datetime.now().isoformat()
                
            # Calculate test statistics for this execution
            completed_tests = 0
            failed_tests = 0
            total_tests = 0
            
            # Get all runs for this execution ID
            runs = self.get_runs_by_execution_id(execution_id)
            if runs:
                total_tests = len(runs)
                for run in runs:
                    if run.get('status') in ['completed', 'passed', 'failed']:
                        completed_tests += 1
                    if run.get('status') == 'failed':
                        failed_tests += 1
            
            # Update the execution metadata to include test statistics
            cursor = self.conn.cursor()
            
            # Get current metadata
            cursor.execute("SELECT metadata FROM executions WHERE execution_id = ?", (execution_id,))
            row = cursor.fetchone()
            
            metadata_dict = {}
            if row and row[0]:
                try:
                    metadata_str = row[0]
                    metadata_dict = json.loads(metadata_str)
                except (json.JSONDecodeError, TypeError):
                    logger.warning(f"Invalid metadata for execution {execution_id}, creating new metadata")
                    metadata_dict = {}
            
            # Update metadata with test statistics
            metadata_dict.update({
                'completed_tests': completed_tests,
                'failed_tests': failed_tests,
                'total_tests': total_tests,
                'status': status,
                'updated_at': datetime.datetime.now().isoformat()
            })
            
            # Convert back to JSON string
            metadata_json = json.dumps(metadata_dict)
            
            # Update the execution record
            cursor.execute(
                '''
                UPDATE executions 
                SET status = ?, end_time = ?, metadata = ?
                WHERE execution_id = ?
                ''',
                (status, end_time, metadata_json, execution_id)
            )
            
            # If record doesn't exist, create it
            if cursor.rowcount == 0:
                start_time = datetime.datetime.now().isoformat()
                cursor.execute(
                    '''
                    INSERT INTO executions (execution_id, status, start_time, end_time, metadata)
                    VALUES (?, ?, ?, ?, ?)
                    ''',
                    (execution_id, status, start_time, end_time, metadata_json)
                )
            
            self.conn.commit()
            self.flush()  # Ensure data is written to disk immediately
            logger.debug(f"Updated execution {execution_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"Error updating execution status: {e}")
            self.conn.rollback()
            return False
    
    def get_runs_by_execution_id(self, execution_id):
        """Get all test runs associated with an execution ID."""
        try:
            runs = self.get_all_runs()
            matching_runs = []
            
            for run in runs:
                try:
                    # Extract and parse metadata
                    metadata = run.get('metadata')
                    if isinstance(metadata, str):
                        metadata = json.loads(metadata)
                    
                    # Check if this run belongs to our execution
                    if metadata and metadata.get('execution_id') == execution_id:
                        matching_runs.append(run)
                except (json.JSONDecodeError, TypeError):
                    # Skip runs with invalid metadata
                    continue
                    
            return matching_runs
        except Exception as e:
            self.logger.error(f"Error getting runs by execution ID: {e}")
            return []
    
    def _ensure_executions_table(self):
        """Ensure the executions table exists."""
        query = """
            CREATE TABLE IF NOT EXISTS executions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id TEXT NOT NULL,
                status TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT,
                metadata TEXT,
                UNIQUE(execution_id)
            )
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(query)
            self.conn.commit()
        except Exception as e:
            self.logger.error(f"Error creating executions table: {e}")
    
    def _initialize_db(self):
        """Initialize the database schema."""
        # Ensure all tables exist
        self.conn.row_factory = sqlite3.Row
        self._ensure_runs_table()
        self._ensure_steps_table()
        self._ensure_events_table()
        self._ensure_executions_table()
    
    def get_run(self, run_id: int) -> Dict[str, Any]:
        """Get information about a specific test run.
        
        Args:
            run_id: ID of the run to retrieve
            
        Returns:
            Run record as a dictionary, or None if not found
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                '''
                SELECT * FROM runs
                WHERE id = ?
                ''',
                (run_id,)
            )
            row = cursor.fetchone()
            if row:
                run_data = dict(row)
                # Parse JSON fields
                if run_data.get("metadata") and isinstance(run_data["metadata"], str):
                    try:
                        run_data["metadata"] = json.loads(run_data["metadata"])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse metadata JSON for run {run_id}, converting to dictionary")
                        # Convert to a simple dict to avoid get() errors
                        run_data["metadata"] = {"raw_value": run_data["metadata"]}
                return run_data
            return None
        except sqlite3.Error as e:
            logger.error(f"Error retrieving run record: {e}")
            raise

    def get_all_runs(self) -> List[Dict[str, Any]]:
        """Get all test runs from the database.
        
        Returns:
            List of run records as dictionaries
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM runs ORDER BY start_time DESC')
            rows = cursor.fetchall()
            runs = []
            for row in rows:
                run_data = dict(row)
                # Parse JSON fields
                if run_data.get("metadata") and isinstance(run_data["metadata"], str):
                    try:
                        run_data["metadata"] = json.loads(run_data["metadata"])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse metadata JSON for run {run_data.get('id')}, converting to dictionary")
                        # Convert to a simple dict to avoid get() errors
                        run_data["metadata"] = {"raw_value": run_data["metadata"]}
                runs.append(run_data)
            return runs
        except sqlite3.Error as e:
            logger.error(f"Error retrieving all run records: {e}")
            return []
    
    def get_run_events(self, run_id: int, step_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get all events for a specific test run or step.
        
        Args:
            run_id: ID of the run to retrieve events for
            step_id: Optional ID of the step to filter events by
            
        Returns:
            List of event information dictionaries
        """
        try:
            cursor = self.conn.cursor()
            if step_id:
                cursor.execute(
                    "SELECT * FROM events WHERE run_id = ? AND step_id = ? ORDER BY timestamp",
                    (run_id, step_id)
                )
            else:
                cursor.execute(
                    "SELECT * FROM events WHERE run_id = ? ORDER BY timestamp",
                    (run_id,)
                )
            rows = cursor.fetchall()
            events = []
            for row in rows:
                event = dict(row)
                # Parse JSON fields
                if event.get("data") and isinstance(event["data"], str):
                    try:
                        event["data"] = json.loads(event["data"])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse event data JSON for event {event.get('id')}, converting to dictionary")
                        # Convert to a simple dict to avoid get() errors
                        event["data"] = {"raw_value": event["data"]}
                events.append(event)
            return events
        except sqlite3.Error as e:
            logger.error(f"Error retrieving events: {e}")
            return []
    
    def get_recent_runs(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent test runs.
        
        Args:
            limit: Maximum number of runs to retrieve
            
        Returns:
            List of run information dictionaries
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT * FROM runs ORDER BY start_time DESC LIMIT ?",
                (limit,)
            )
            rows = cursor.fetchall()
            runs = []
            for row in rows:
                run = dict(row)
                # Parse JSON fields
                if run.get("metadata") and isinstance(run["metadata"], str):
                    try:
                        run["metadata"] = json.loads(run["metadata"])
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse metadata JSON for run {run.get('id')}, converting to dictionary")
                        # Convert to a simple dict to avoid get() errors
                        run["metadata"] = {"raw_value": run["metadata"]}
                runs.append(run)
            return runs
        except sqlite3.Error as e:
            logger.error(f"Error retrieving recent runs: {e}")
            return []
    
    def get_run_statistics(self, test_id: Optional[str] = None) -> Dict[str, Any]:
        """Get statistics about test runs.
        
        Args:
            test_id: Optional test ID to filter statistics by
            
        Returns:
            Dictionary containing statistics
        """
        try:
            cursor = self.conn.cursor()
            
            # Base query parts
            select_clause = """
                COUNT(*) as total_runs,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_runs,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_runs,
                SUM(CASE WHEN status = 'aborted' THEN 1 ELSE 0 END) as aborted_runs,
                SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) as running_runs
            """
            
            if test_id:
                cursor.execute(
                    f"SELECT {select_clause} FROM runs WHERE test_id = ?",
                    (test_id,)
                )
            else:
                cursor.execute(f"SELECT {select_clause} FROM runs")
            
            row = cursor.fetchone()
            return dict(row)
        except sqlite3.Error as e:
            logger.error(f"Error retrieving run statistics: {e}")
            return {"total_runs": 0, "completed_runs": 0, "failed_runs": 0, "aborted_runs": 0, "running_runs": 0}
    
    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.debug("Database connection closed")

    def get_all_executions(self):
        """Get all execution records from the database."""
        try:
            query = "SELECT * FROM executions ORDER BY start_time DESC"
            cursor = self.conn.cursor()
            cursor.execute(query)
            
            executions = []
            for row in cursor.fetchall():
                executions.append(dict(row))
            
            return executions
        except Exception as e:
            self.logger.error(f"Error retrieving all executions: {e}")
            return []

    def store_xml_test_results(self, execution_id: str, test_id: str, xml_file_path: str) -> Optional[int]:
        """Store XML test results in the database.
        
        Args:
            execution_id: ID of the test execution
            test_id: ID of the test
            xml_file_path: Path to the XML result file
            
        Returns:
            ID of the created record or None if failed
        """
        try:
            import xml.etree.ElementTree as ET
            
            # Check if file exists
            if not os.path.exists(xml_file_path):
                logger.error(f"XML file not found: {xml_file_path}")
                return None
            
            # Parse XML file
            tree = ET.parse(xml_file_path)
            root = tree.getroot()
            
            # Extract testsuite data
            testsuite = root.find('.//testsuite')
            if testsuite is None:
                logger.error(f"No testsuite element found in XML: {xml_file_path}")
                return None
            
            testsuite_name = testsuite.get('name', '')
            tests_count = int(testsuite.get('tests', 0))
            errors_count = int(testsuite.get('errors', 0))
            failures_count = int(testsuite.get('failures', 0))
            skipped_count = int(testsuite.get('skipped', 0))
            time = float(testsuite.get('time', 0))
            timestamp = testsuite.get('timestamp', '')
            
            # Extract testcase data
            testcase = testsuite.find('.//testcase')
            if testcase is None:
                logger.error(f"No testcase element found in XML: {xml_file_path}")
                return None
            
            test_name = testcase.get('name', '')
            test_classname = testcase.get('classname', '')
            test_time = float(testcase.get('time', 0))
            
            # Extract system-out
            system_out_elem = testcase.find('.//system-out')
            system_out = system_out_elem.text if system_out_elem is not None and system_out_elem.text else ''
            
            # Extract properties
            property_terminate = ''
            property_feature_file = ''
            property_output_file = ''
            property_proofs_video = ''
            property_proofs_base_folder = ''
            property_proofs_screenshot = ''
            property_network_logs = ''
            property_agents_logs = ''
            property_planner_thoughts = ''
            property_plan = ''
            property_next_step = ''
            property_terminate_flag = ''
            property_target_helper = ''
            
            properties = testcase.find('.//properties')
            if properties is not None:
                for prop in properties.findall('.//property'):
                    name = prop.get('name', '')
                    value = prop.get('value', '')
                    
                    if name == 'Terminate':
                        property_terminate = value
                    elif name == 'Feature File':
                        property_feature_file = value
                    elif name == 'Output File':
                        property_output_file = value
                    elif name == 'Proofs Video':
                        property_proofs_video = value
                    elif name == 'Proofs Base Folder, includes screenshots, recording, netwrok logs, api logs, sec logs, accessibility logs':
                        property_proofs_base_folder = value
                    elif name == 'Proofs Screenshot':
                        property_proofs_screenshot = value
                    elif name == 'Network Logs':
                        property_network_logs = value
                    elif name == 'Agents Internal Logs':
                        property_agents_logs = value
                    elif name == 'Planner Thoughts':
                        property_planner_thoughts = value
                    elif name == 'plan':
                        property_plan = value
                    elif name == 'next_step':
                        property_next_step = value
                    elif name == 'terminate':
                        property_terminate_flag = value
                    elif name == 'target_helper':
                        property_target_helper = value
            
            # Extract final response
            final_response = ''
            system_out_elements = testcase.findall('.//system-out')
            if len(system_out_elements) > 1:
                final_response = system_out_elements[1].text if system_out_elements[1].text else ''
            
            # Determine if test passed based on final_response content
            test_passed = False
            if final_response:
                # Check for positive indicators in the final response
                positive_indicators = [
                    "test scenario passed", 
                    "test passed",
                    "successfully",
                    "all validations passed"
                ]
                # Check for negative indicators
                negative_indicators = [
                    "test scenario failed",
                    "test failed",
                    "error",
                    "exception",
                    "validation failed"
                ]
                
                # Convert to lowercase for case-insensitive matching
                final_response_lower = final_response.lower()
                
                # Check if any positive indicators exist
                has_positive = any(indicator.lower() in final_response_lower for indicator in positive_indicators)
                # Check if any negative indicators exist
                has_negative = any(indicator.lower() in final_response_lower for indicator in negative_indicators)
                
                # Consider the test passed if it has positive indicators and no negative ones,
                # or if no errors/failures are reported in the testsuite
                if has_positive and not has_negative:
                    test_passed = True
                elif not has_negative and errors_count == 0 and failures_count == 0:
                    test_passed = True
                
                logger.info(f"Test result determination: passed={test_passed}, based on response: '{final_response[:100]}...'")
            else:
                # If no final_response, check if the testsuite has any errors or failures
                test_passed = errors_count == 0 and failures_count == 0
                logger.info(f"No final response found, test result determination based on errors/failures: passed={test_passed}")
            
            # Extract total execution stats
            total_execution_cost = 0.0
            total_token_used = 0
            
            testsuite_properties = testsuite.find('.//properties')
            if testsuite_properties is not None:
                for prop in testsuite_properties.findall('.//property'):
                    name = prop.get('name', '')
                    value = prop.get('value', '')
                    
                    if name == 'total_execution_cost':
                        total_execution_cost = float(value) if value else 0.0
                    elif name == 'total_token_used':
                        total_token_used = int(value) if value else 0
            
            # Transform all paths to point to permanent storage location
            from src.utils.paths import get_data_dir
            data_dir = get_data_dir()
            
            # Define path patterns for transformation
            exec_path_pattern = str(data_dir / "manager" / "exec" / f"run_{execution_id}")
            archive_path_pattern = str(data_dir / "manager" / "perm" / "ExecutionResultHistory" / f"run_{execution_id}")
            
            # Function to transform paths
            def transform_path(path_str):
                if path_str and exec_path_pattern in path_str:
                    return path_str.replace(exec_path_pattern, archive_path_pattern)
                return path_str
            
            # Transform all path properties
            property_feature_file = transform_path(property_feature_file)
            property_output_file = transform_path(property_output_file)
            property_proofs_video = transform_path(property_proofs_video)
            property_proofs_base_folder = transform_path(property_proofs_base_folder)
            property_proofs_screenshot = transform_path(property_proofs_screenshot)
            property_network_logs = transform_path(property_network_logs)
            property_agents_logs = transform_path(property_agents_logs)
            property_planner_thoughts = transform_path(property_planner_thoughts)
            
            logger.info(f"Transformed paths to reference permanent storage location: {archive_path_pattern}")
            
            # Get run_id if it exists
            run_id = None
            cursor = self.conn.cursor()
            cursor.execute(
                '''
                SELECT id FROM runs 
                WHERE test_id = ? 
                ORDER BY start_time DESC 
                LIMIT 1
                ''',
                (test_id,)
            )
            result = cursor.fetchone()
            if result:
                run_id = result[0]
            
            # Insert data into database
            cursor.execute(
                '''
                INSERT OR REPLACE INTO test_xml_results (
                    run_id, execution_id, test_id, testsuite_name, tests_count, errors_count, failures_count,
                    skipped_count, time, timestamp, test_name, test_classname, test_time, system_out,
                    property_terminate, property_feature_file, property_output_file, property_proofs_video,
                    property_proofs_base_folder, property_proofs_screenshot, property_network_logs,
                    property_agents_logs, property_planner_thoughts, property_plan, property_next_step,
                    property_terminate_flag, property_target_helper, final_response, total_execution_cost,
                    total_token_used, xml_file_path, test_passed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    run_id, execution_id, test_id, testsuite_name, tests_count, errors_count, failures_count,
                    skipped_count, time, timestamp, test_name, test_classname, test_time, system_out,
                    property_terminate, property_feature_file, property_output_file, property_proofs_video,
                    property_proofs_base_folder, property_proofs_screenshot, property_network_logs,
                    property_agents_logs, property_planner_thoughts, property_plan, property_next_step,
                    property_terminate_flag, property_target_helper, final_response, total_execution_cost,
                    total_token_used, xml_file_path, test_passed
                )
            )
            
            self.conn.commit()
            record_id = cursor.lastrowid
            logger.info(f"Stored XML test results for execution {execution_id}, test {test_id}")
            
            # Read back the data to verify it was stored correctly
            try:
                cursor.execute(
                    '''
                    SELECT * FROM test_xml_results WHERE id = ?
                    ''',
                    (record_id,)
                )
                verification_record = cursor.fetchone()
                if verification_record:
                    logger.info(f"Verified XML test results storage: ID={record_id}, execution_id={verification_record[2]}, test_id={verification_record[3]}")
                else:
                    logger.warning(f"Could not verify XML test results with ID={record_id}")
            except Exception as e:
                logger.error(f"Error verifying XML test results: {e}")
            
            return record_id
            
        except sqlite3.Error as e:
            logger.error(f"Error storing XML test results in database: {e}")
            self.conn.rollback()
            return None
        except Exception as e:
            logger.error(f"Error processing XML test results: {e}")
            return None

    def get_xml_test_results(self, execution_id: str = None, test_id: str = None) -> List[Dict[str, Any]]:
        """Get XML test results from the database.
        
        Args:
            execution_id: Filter by execution ID (optional)
            test_id: Filter by test ID (optional)
            
        Returns:
            List of XML test results
        """
        try:
            query = "SELECT * FROM test_xml_results"
            params = []
            
            if execution_id or test_id:
                query += " WHERE"
                
                if execution_id:
                    query += " execution_id = ?"
                    params.append(execution_id)
                    
                    if test_id:
                        query += " AND test_id = ?"
                        params.append(test_id)
                elif test_id:
                    query += " test_id = ?"
                    params.append(test_id)
            
            query += " ORDER BY timestamp DESC"
            
            cursor = self.conn.cursor()
            cursor.execute(query, params)
            results = cursor.fetchall()
            
            # Convert results to list of dictionaries
            results_list = [dict(result) for result in results]
            
            # Process any results that might have paths referring to the temporary location
            for result in results_list:
                exec_id = result.get("execution_id")
                if exec_id:
                    from src.utils.paths import get_data_dir
                    data_dir = get_data_dir()
                    
                    # Define path patterns
                    exec_path_pattern = str(data_dir / "manager" / "exec" / f"run_{exec_id}")
                    archive_path_pattern = str(data_dir / "manager" / "perm" / "ExecutionResultHistory" / f"run_{exec_id}")
                    
                    # List of path properties that might need transformation
                    path_props = [
                        "property_feature_file", "property_output_file", "property_proofs_video",
                        "property_proofs_base_folder", "property_proofs_screenshot", 
                        "property_network_logs", "property_agents_logs", "property_planner_thoughts"
                    ]
                    
                    # Check if the permanent path exists (archiving has occurred)
                    if Path(archive_path_pattern).exists() and not Path(exec_path_pattern).exists():
                        # Transform any paths that reference the temporary location
                        for prop in path_props:
                            if prop in result and result[prop] and exec_path_pattern in result[prop]:
                                result[prop] = result[prop].replace(exec_path_pattern, archive_path_pattern)
                                logger.debug(f"Transformed path in query result for {prop}")
            
            return results_list
        except sqlite3.Error as e:
            logger.error(f"Error retrieving XML test results from database: {e}")
            return []

    def flush(self) -> None:
        """Force an immediate write of all cached database changes to disk."""
        if self.conn:
            self.conn.commit()
            logger.debug("Database flushed to disk")

# Create a global database instance
db = Database() 
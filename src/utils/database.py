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
        if db_path is None:
            # Use default path in data directory
            from src.utils.paths import get_data_dir
            data_dir = get_data_dir()
            db_path = str(data_dir / "execution_runs.db")
        
        self.db_path = db_path
        self.conn = None
        self._connect()
        self._create_tables()
        logger.info(f"Database initialized at {self.db_path}")
    
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
            
            self.conn.commit()
            logger.debug("Database tables created successfully")
        except sqlite3.Error as e:
            logger.error(f"Error creating database tables: {e}")
            raise
    
    def create_run(self, test_id: str, browser_type: str = "chromium", 
                  headless: bool = True, environment: str = "default",
                  metadata: Optional[Dict[str, Any]] = None) -> int:
        """Create a new test run record.
        
        Args:
            test_id: ID or path of the test being executed
            browser_type: Type of browser used for the test
            headless: Whether the browser is running in headless mode
            environment: Environment name (e.g., "production", "staging")
            metadata: Additional metadata as a dictionary
            
        Returns:
            The ID of the created run
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                '''
                INSERT INTO runs (test_id, browser_type, headless, environment, metadata)
                VALUES (?, ?, ?, ?, ?)
                ''',
                (
                    test_id,
                    browser_type,
                    headless,
                    environment,
                    json.dumps(metadata) if metadata else None
                )
            )
            self.conn.commit()
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
    
    def update_step_status(self, step_id: int, status: str, 
                          screenshot_path: Optional[str] = None,
                          error_message: Optional[str] = None) -> None:
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
    
    def log_event(self, run_id: int, event_type: str, message: str, 
                 step_id: Optional[int] = None, 
                 data: Optional[Dict[str, Any]] = None) -> int:
        """Log an event during test execution.
        
        Args:
            run_id: ID of the run this event belongs to
            event_type: Type of event (e.g., "info", "warning", "error")
            message: Event message
            step_id: ID of the step this event belongs to (optional)
            data: Additional data as a dictionary
            
        Returns:
            The ID of the created event
        """
        try:
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
                    json.dumps(data) if data else None
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
    
    def get_run(self, run_id: int) -> Dict[str, Any]:
        """Get information about a specific test run.
        
        Args:
            run_id: ID of the run to retrieve
            
        Returns:
            Run information as a dictionary
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            if row:
                run_data = dict(row)
                # Parse JSON fields
                if run_data.get("metadata"):
                    run_data["metadata"] = json.loads(run_data["metadata"])
                return run_data
            return {}
        except sqlite3.Error as e:
            logger.error(f"Error retrieving run: {e}")
            raise
    
    def get_run_steps(self, run_id: int) -> List[Dict[str, Any]]:
        """Get all steps for a specific test run.
        
        Args:
            run_id: ID of the run to retrieve steps for
            
        Returns:
            List of step information dictionaries
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT * FROM steps WHERE run_id = ? ORDER BY step_index", (run_id,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error(f"Error retrieving run steps: {e}")
            raise
    
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
                if event.get("data"):
                    event["data"] = json.loads(event["data"])
                events.append(event)
            return events
        except sqlite3.Error as e:
            logger.error(f"Error retrieving events: {e}")
            raise
    
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
                if run.get("metadata"):
                    run["metadata"] = json.loads(run["metadata"])
                runs.append(run)
            return runs
        except sqlite3.Error as e:
            logger.error(f"Error retrieving recent runs: {e}")
            raise
    
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
            raise
    
    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            self.conn.close()
            logger.debug("Database connection closed")

# Create a global database instance
db = Database() 
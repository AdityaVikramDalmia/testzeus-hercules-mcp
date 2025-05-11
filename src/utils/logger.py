import logging
import os
import sys
from typing import Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

class Logger:
    """Simple logger wrapper with enhanced functionality."""
    
    def __init__(self, name: str = "mcp-server"):
        self.logger = logging.getLogger(name)
        self.debug_enabled = os.getenv("SERVER_DEBUG", "false").lower() == "true"
        
        # Set log level based on environment
        if self.debug_enabled:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)
    
    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.debug(msg, *args, **kwargs)
    
    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.error(msg, *args, **kwargs)
    
    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self.logger.critical(msg, *args, **kwargs)
    
    def setLevel(self, level: int) -> None:
        """Set the logging level of this logger.
        
        Args:
            level: The logging level to set (e.g., logging.INFO, logging.DEBUG)
        """
        self.logger.setLevel(level)
    
    def addHandler(self, handler: logging.Handler) -> None:
        """Add the specified handler to this logger.
        
        Args:
            handler: The handler to add
        """
        self.logger.addHandler(handler)

# Create a global logger instance
logger = Logger() 
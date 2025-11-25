"""File watcher service to monitor scan folder for new documents."""

import logging
import time
import threading
from pathlib import Path
from typing import Callable, Optional
from datetime import datetime

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileCreatedEvent

from app.config import SCAN_FOLDER_PATH, SUPPORTED_EXTENSIONS

logger = logging.getLogger(__name__)


class DocumentHandler(FileSystemEventHandler):
    """Handler for file system events in the scan folder."""
    
    def __init__(self, process_callback: Callable[[Path], None]):
        """
        Initialize the document handler.
        
        Args:
            process_callback: Function to call when a new document is detected
        """
        super().__init__()
        self.process_callback = process_callback
        self.processing_files = set()
        self.lock = threading.Lock()
    
    def on_created(self, event):
        """Handle file creation events."""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path).resolve()
        
        # Check if it's a supported file type
        if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        
        # Avoid processing the same file multiple times
        with self.lock:
            if str(file_path) in self.processing_files:
                return
            self.processing_files.add(str(file_path))
        
        # Wait for file to be fully written
        self._wait_for_file_ready(file_path)
        
        try:
            logger.info(f"New document detected: {file_path}")
            self.process_callback(file_path)
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
        finally:
            with self.lock:
                self.processing_files.discard(str(file_path))
    
    def _wait_for_file_ready(self, file_path: Path, timeout: int = 30):
        """
        Wait for a file to be fully written (size stops changing).
        
        Args:
            file_path: Path to the file
            timeout: Maximum seconds to wait
        """
        last_size = -1
        stable_count = 0
        start_time = time.time()
        
        while stable_count < 3 and (time.time() - start_time) < timeout:
            try:
                current_size = file_path.stat().st_size
                
                if current_size == last_size:
                    stable_count += 1
                else:
                    stable_count = 0
                    last_size = current_size
                
                time.sleep(0.5)
            except FileNotFoundError:
                # File might have been moved/deleted
                break


class FileWatcherService:
    """Service for monitoring the scan folder for new documents."""
    
    def __init__(self):
        """Initialize the file watcher service."""
        self.scan_folder = SCAN_FOLDER_PATH
        self.observer: Optional[Observer] = None
        self.process_callback: Optional[Callable[[Path], None]] = None
        self.is_running = False
        
        # Ensure scan folder exists
        self.scan_folder.mkdir(parents=True, exist_ok=True)
        logger.info(f"File watcher initialized for: {self.scan_folder}")
    
    def set_process_callback(self, callback: Callable[[Path], None]):
        """
        Set the callback function for processing new documents.
        
        Args:
            callback: Function to call when a new document is detected
        """
        self.process_callback = callback
    
    def start(self):
        """Start watching the scan folder."""
        if self.is_running:
            logger.warning("File watcher is already running")
            return
        
        if not self.process_callback:
            raise ValueError("Process callback must be set before starting")
        
        self.observer = Observer()
        handler = DocumentHandler(self.process_callback)
        
        self.observer.schedule(handler, str(self.scan_folder), recursive=False)
        self.observer.start()
        self.is_running = True
        
        logger.info(f"Started watching folder: {self.scan_folder}")
    
    def stop(self):
        """Stop watching the scan folder."""
        if self.observer and self.is_running:
            self.observer.stop()
            self.observer.join()
            self.is_running = False
            logger.info("File watcher stopped")
    
    def process_existing_files(self):
        """Process any existing files in the scan folder."""
        if not self.process_callback:
            raise ValueError("Process callback must be set before processing")
        
        logger.info("Checking for existing files in scan folder...")
        
        for file_path in self.scan_folder.iterdir():
            if file_path.is_file() and file_path.suffix.lower() in SUPPORTED_EXTENSIONS:
                try:
                    logger.info(f"Processing existing file: {file_path}")
                    self.process_callback(file_path)
                except Exception as e:
                    logger.error(f"Error processing existing file {file_path}: {e}")


# Global file watcher service instance
file_watcher_service = FileWatcherService()


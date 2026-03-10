"""
Virus scanning utilities for uploaded files.

Supports multiple scanning backends:
- ClamAV (local or remote daemon)
- Cloud-based scanning services (extensible)
- Mock scanner for testing/development

Configuration via environment variables:
- VIRUS_SCAN_ENABLED: Enable/disable scanning (default: True)
- VIRUS_SCAN_BACKEND: Scanner backend ('clamav', 'mock', default: 'clamav')
- CLAMAV_HOST: ClamAV daemon host (default: 'localhost')
- CLAMAV_PORT: ClamAV daemon port (default: 3310)
- CLAMAV_TIMEOUT: Connection timeout in seconds (default: 30)
"""

import os
import socket
import logging
from typing import Tuple, Optional
from abc import ABC, abstractmethod
from django.conf import settings


logger = logging.getLogger(__name__)


class VirusScanError(Exception):
    """Raised when virus scanning encounters an error."""
    pass


class VirusDetectedError(Exception):
    """Raised when a virus is detected in a file."""
    pass


class VirusScannerBackend(ABC):
    """Abstract base class for virus scanner backends."""
    
    @abstractmethod
    def scan_file(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Scan a file for viruses.
        
        Args:
            file_path: Path to the file to scan
            
        Returns:
            Tuple of (is_clean, virus_name)
            - (True, None) if file is clean
            - (False, virus_name) if virus detected
            
        Raises:
            VirusScanError: If scanning fails
        """
        pass


class ClamAVScanner(VirusScannerBackend):
    """
    ClamAV virus scanner backend.
    
    Connects to ClamAV daemon (clamd) via TCP socket and uses the INSTREAM
    command to scan file contents.
    """
    
    def __init__(self, host: str = 'localhost', port: int = 3310, timeout: int = 30):
        """
        Initialize ClamAV scanner.
        
        Args:
            host: ClamAV daemon host
            port: ClamAV daemon port
            timeout: Connection timeout in seconds
        """
        self.host = host
        self.port = port
        self.timeout = timeout
    
    def _send_command(self, sock: socket.socket, command: bytes) -> bytes:
        """Send command to ClamAV and receive response."""
        sock.sendall(command)
        response = b''
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            response += chunk
            if b'\x00' in chunk:  # ClamAV terminates responses with null byte
                break
        return response
    
    def scan_file(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """
        Scan file using ClamAV INSTREAM command.
        
        The INSTREAM command allows streaming file contents to ClamAV,
        which is more secure than passing file paths.
        """
        try:
            # Connect to ClamAV daemon
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.host, self.port))
            
            try:
                # Send INSTREAM command
                sock.sendall(b'zINSTREAM\x00')
                
                # Stream file contents in chunks
                with open(file_path, 'rb') as f:
                    while True:
                        chunk = f.read(4096)
                        if not chunk:
                            break
                        
                        # Send chunk size (4 bytes, network byte order)
                        size = len(chunk).to_bytes(4, byteorder='big')
                        sock.sendall(size)
                        sock.sendall(chunk)
                
                # Send zero-length chunk to signal end of stream
                sock.sendall(b'\x00\x00\x00\x00')
                
                # Receive response
                response = sock.recv(4096).decode('utf-8').strip()
                
                # Parse response
                # Format: "stream: OK" or "stream: <virus_name> FOUND"
                if 'OK' in response:
                    logger.info(f"File {file_path} is clean (ClamAV)")
                    return True, None
                elif 'FOUND' in response:
                    # Extract virus name and strip whitespace and null bytes
                    virus_name = response.split(':')[1].replace('FOUND', '').strip().rstrip('\x00').strip()
                    logger.warning(f"Virus detected in {file_path}: {virus_name}")
                    return False, virus_name
                else:
                    raise VirusScanError(f"Unexpected ClamAV response: {response}")
            
            finally:
                sock.close()
        
        except socket.timeout:
            raise VirusScanError(f"ClamAV connection timeout after {self.timeout}s")
        except socket.error as e:
            raise VirusScanError(f"ClamAV connection error: {e}")
        except FileNotFoundError:
            raise VirusScanError(f"File not found: {file_path}")
        except Exception as e:
            raise VirusScanError(f"ClamAV scan error: {e}")


class MockScanner(VirusScannerBackend):
    """
    Mock virus scanner for testing and development.
    
    Detects "viruses" based on filename patterns:
    - Files containing 'virus' or 'malware' in name are flagged
    - All other files are considered clean
    """
    
    def scan_file(self, file_path: str) -> Tuple[bool, Optional[str]]:
        """Mock scan that checks filename for test patterns."""
        filename = os.path.basename(file_path).lower()
        
        if 'virus' in filename or 'malware' in filename:
            logger.warning(f"Mock scanner: Virus detected in {file_path}")
            return False, "Test.Virus.Mock"
        
        logger.info(f"Mock scanner: File {file_path} is clean")
        return True, None


def get_scanner_backend() -> VirusScannerBackend:
    """
    Get configured virus scanner backend.
    
    Returns:
        Configured scanner backend instance
    """
    backend = getattr(settings, 'VIRUS_SCAN_BACKEND', 'clamav').lower()
    
    if backend == 'clamav':
        host = getattr(settings, 'CLAMAV_HOST', 'localhost')
        port = getattr(settings, 'CLAMAV_PORT', 3310)
        timeout = getattr(settings, 'CLAMAV_TIMEOUT', 30)
        return ClamAVScanner(host=host, port=port, timeout=timeout)
    
    elif backend == 'mock':
        return MockScanner()
    
    else:
        raise ValueError(f"Unknown virus scanner backend: {backend}")


def is_virus_scan_enabled() -> bool:
    """
    Check if virus scanning is enabled.
    
    Returns:
        True if scanning is enabled, False otherwise
    """
    return getattr(settings, 'VIRUS_SCAN_ENABLED', True)


def scan_file(file_path: str) -> Tuple[bool, Optional[str]]:
    """
    Scan a file for viruses using the configured backend.
    
    Args:
        file_path: Path to the file to scan
        
    Returns:
        Tuple of (is_clean, virus_name)
        - (True, None) if file is clean or scanning is disabled
        - (False, virus_name) if virus detected
        
    Raises:
        VirusScanError: If scanning fails
    """
    if not is_virus_scan_enabled():
        logger.info("Virus scanning is disabled")
        return True, None
    
    scanner = get_scanner_backend()
    return scanner.scan_file(file_path)


def scan_file_or_raise(file_path: str) -> None:
    """
    Scan file and raise VirusDetectedError if virus found.
    
    Args:
        file_path: Path to the file to scan
        
    Raises:
        VirusDetectedError: If virus is detected
        VirusScanError: If scanning fails
    """
    is_clean, virus_name = scan_file(file_path)
    
    if not is_clean:
        raise VirusDetectedError(f"Virus detected: {virus_name}")

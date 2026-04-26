import os
import socket
import logging


def get_local_ip() -> str:
    """Get the local IP address of the machine."""
    try:
        # Connect to an external host to determine the local IP
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
        return local_ip
    except Exception as e:
        logging.error(f"Error occurred while fetching local IP: {e}")
        return os.getenv("DSKITY_HOST", "0.0.0.0")


def get_current_host_port() -> tuple[str, int]:
    """Get the current host and port from environment variables or defaults."""
    return get_local_ip(), int(os.getenv("DSKITY_PORT", "8000"))

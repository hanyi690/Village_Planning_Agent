"""
Path utilities for data directory access

Provides consistent access to data directories across the application.
"""

from pathlib import Path
from app.core.settings import DATA_DIR


def get_data_dir() -> Path:
    """
    Get the data directory path.

    Returns:
        Path to the data directory (PROJECT_ROOT/data)
    """
    return DATA_DIR


def get_reports_dir() -> Path:
    """
    Get the reports storage directory.

    Returns:
        Path to the reports directory (DATA_DIR/reports)
    """
    return DATA_DIR / "reports"


def ensure_dir(path: Path) -> Path:
    """
    Ensure a directory exists, creating it if necessary.

    Args:
        path: Directory path to ensure

    Returns:
        The ensured path
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


__all__ = ["get_data_dir", "get_reports_dir", "ensure_dir"]
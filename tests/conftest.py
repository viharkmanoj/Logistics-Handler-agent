"""
Pytest configuration and shared fixtures.
Provides isolated temporary SQLite database instances for each test run.
"""

import os
import tempfile
import pytest
from pathlib import Path

from logistics.database import init_db


@pytest.fixture
def temp_db(tmp_path: Path):
    """
    Fixture providing an isolated, clean SQLite database per test.
    Initializes tables and seeds initial sample inventory.
    """
    db_file = tmp_path / "test_logistics.db"
    db_str = str(db_file)
    init_db(db_str)
    yield db_str

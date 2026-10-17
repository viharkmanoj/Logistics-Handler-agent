"""
Configuration management for the Logistics Handler AI Agent.
"""

import os
from pathlib import Path
from typing import Dict, List
from dotenv import load_dotenv

# Load environment variables from .env file if present
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = os.getenv("LOGISTICS_DB_PATH", str(BASE_DIR / "data" / "logistics.db"))

# Google Gemini & Google ADK Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", "")).strip()
GOOGLE_API_KEY = GEMINI_API_KEY
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", os.getenv("ROUTING_API_KEY", "")).strip()

# Mode: 'auto', 'ai', or 'demo'
AGENT_MODE = os.getenv("AGENT_MODE", "auto").lower()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Transient failure simulation counter (for demonstrating self-healing)
SIMULATE_TRANSIENT_FAILURES = int(os.getenv("SIMULATE_TRANSIENT_FAILURES", "0"))

# Permitted shipment statuses
STATUS_CREATED = "CREATED"
STATUS_IN_TRANSIT = "IN_TRANSIT"
STATUS_OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
STATUS_DELIVERED = "DELIVERED"
STATUS_CANCELLED = "CANCELLED"

ALL_STATUSES = [
    STATUS_CREATED,
    STATUS_IN_TRANSIT,
    STATUS_OUT_FOR_DELIVERY,
    STATUS_DELIVERED,
    STATUS_CANCELLED,
]

# State machine for valid shipment status transitions
VALID_TRANSITIONS: Dict[str, List[str]] = {
    STATUS_CREATED: [STATUS_IN_TRANSIT, STATUS_CANCELLED],
    STATUS_IN_TRANSIT: [STATUS_OUT_FOR_DELIVERY, STATUS_CANCELLED],
    STATUS_OUT_FOR_DELIVERY: [STATUS_DELIVERED, STATUS_CANCELLED],
    STATUS_DELIVERED: [],
    STATUS_CANCELLED: [],
}

# Standard inventory seed
INITIAL_INVENTORY = {
    "Laptop": 50,
    "Phone": 100,
    "Headphones": 30,
}

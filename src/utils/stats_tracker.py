import os
import json
import httpx
import asyncio
from datetime import datetime
from typing import Dict, Any
from loguru import logger

class StatsTracker:
    """
    HTTP Client for pushing Maya's metrics and leads to the Dashboard API.
    Decouples voice bot performance from persistence/log-parsing concerns.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(StatsTracker, cls).__new__(cls)
            cls._instance._initialise()
        return cls._instance

    def _initialise(self):
        # The Dashboard API always runs on port 8001
        self.api_url = "http://localhost:8001/api"
        # Shared client for sync/async operations
        self.client = httpx.Client(timeout=5.0)
        self.async_client = httpx.AsyncClient(timeout=5.0)

    def increment(self, key: str, amount: int = 1):
        """Atomic increment of a specific stat counter via the Dashboard API."""
        try:
            self.client.post(
                f"{self.api_url}/stats/increment", 
                json={"key": key, "amount": amount}
            )
        except Exception as e:
            logger.warning(f"StatsTracker: Failed to increment '{key}': {e}")

    def log_lead_audit(self, lead_data: Dict[str, Any]):
        """Push a structured lead audit to the Dashboard API."""
        try:
            # Maya's LeadManager provides record_id, session_id, name, email, phone, product, summary
            self.client.post(f"{self.api_url}/leads", json=lead_data)
        except Exception as e:
            logger.warning(f"StatsTracker: Failed to push lead audit: {e}")

# Global singleton instance
# Use 'from src.utils.stats_tracker import stats_tracker' to import
stats_tracker = StatsTracker()

"""WattTime credentials — load from environment only (never commit secrets)."""
from __future__ import annotations

import os

WATTTIME_USERNAME = os.environ.get("WATTTIME_USERNAME", "").strip()
WATTTIME_PASSWORD = os.environ.get("WATTTIME_PASSWORD", "").strip()
EMAIL = os.environ.get("WATTTIME_EMAIL", "").strip()
ORG = os.environ.get("WATTTIME_ORG", "").strip()

# Location to validate region lookup and data fetch (Eugene, Oregon)
TEST_LAT = float(os.environ.get("WATTTIME_TEST_LAT", "44.0521"))
TEST_LON = float(os.environ.get("WATTTIME_TEST_LON", "-123.0868"))

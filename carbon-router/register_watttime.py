"""One-off WattTime account registration. Credentials come from the environment."""
from __future__ import annotations

import os
import sys

import requests

username = os.environ.get("WATTTIME_USERNAME", "").strip()
password = os.environ.get("WATTTIME_PASSWORD", "").strip()
email = os.environ.get("WATTTIME_EMAIL", "").strip()
org = os.environ.get("WATTTIME_ORG", "").strip()

if not all([username, password, email, org]):
    print(
        "Set WATTTIME_USERNAME, WATTTIME_PASSWORD, WATTTIME_EMAIL, and WATTTIME_ORG "
        "before running this script.",
        file=sys.stderr,
    )
    sys.exit(1)

register_url = "https://api.watttime.org/register"
params = {
    "username": username,
    "password": password,
    "email": email,
    "org": org,
}
rsp = requests.post(register_url, json=params)
print(rsp.status_code)
print(rsp.text)

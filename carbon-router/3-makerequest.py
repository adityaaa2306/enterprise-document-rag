import requests
import importlib.util
import sys
from requests.auth import HTTPBasicAuth


def load_settings():
    spec = importlib.util.spec_from_file_location("settings", "settings.py")
    if spec is None or spec.loader is None:
        print("settings.py not found. Please copy settings.py.template to settings.py and fill in your values.")
        sys.exit(1)
    settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(settings)  # type: ignore[attr-defined]
    return settings


def get_token(username: str, password: str) -> str:
    url = "https://api.watttime.org/login"
    rsp = requests.get(url, auth=HTTPBasicAuth(username, password))
    rsp.raise_for_status()
    return rsp.json()["token"]


def main():
    s = load_settings()
    token = get_token(s.WATTTIME_USERNAME, s.WATTTIME_PASSWORD)

    # Resolve region from test lat/lon
    region = "CAISO_NORTH"
    headers = {"Authorization": f"Bearer {token}"}

    # Try a 0-horizon forecast (single point)
    fc_url = "https://api.watttime.org/v3/forecast"
    fc_params = {"region": region, "signal_type": "co2_moer", "horizon_hours": 0}
    fc_rsp = requests.get(fc_url, headers=headers, params=fc_params)
    print(fc_rsp.status_code)
    print(fc_rsp.text)


if __name__ == "__main__":
    main()



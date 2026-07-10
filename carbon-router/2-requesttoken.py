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


def main():
    s = load_settings()
    url = "https://api.watttime.org/login"
    rsp = requests.get(url, auth=HTTPBasicAuth(s.WATTTIME_USERNAME, s.WATTTIME_PASSWORD))
    print(rsp.status_code)
    print(rsp.text)


if __name__ == "__main__":
    main()



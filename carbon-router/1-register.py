import requests
import importlib.util
import sys


def load_settings():
    spec = importlib.util.spec_from_file_location("settings", "settings.py")
    if spec is None or spec.loader is None:
        print("settings.py not found. Please copy settings.py.template to settings.py and fill in your values.")
        sys.exit(1)
    settings = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(settings) 
    return settings


def main():
    s = load_settings()
    url = "https://api.watttime.org/register"
    params = {
        "username": s.WATTTIME_USERNAME,
        "password": s.WATTTIME_PASSWORD,
        "email": s.EMAIL,
        "org": s.ORG,
    }
    rsp = requests.post(url, json=params)
    print(rsp.status_code)
    print(rsp.text)


if __name__ == "__main__":
    main()



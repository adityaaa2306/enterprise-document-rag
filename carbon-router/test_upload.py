import requests

url = "http://localhost:8001/analyze-pdf"
files = {'file': open('sample.pdf', 'rb')}

try:
    response = requests.post(url, files=files)
    print(response.status_code)
    print(response.json())
except requests.exceptions.RequestException as e:
    print(f"Request failed: {e}")
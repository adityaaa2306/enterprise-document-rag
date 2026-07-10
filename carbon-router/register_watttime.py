import requests
register_url = 'https://api.watttime.org/register'
params = {
    'username': 'asmitaverma',
    'password': 'Asmitaverma21#',
    'email': 'asmitaverma@example.com',
    'org': 'techm'
}
rsp = requests.post(register_url, json=params)
print(rsp.status_code)
print(rsp.text)

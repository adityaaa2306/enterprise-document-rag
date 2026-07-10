"""
Quick test to verify CORS is working for auth endpoints
"""
import requests

# Test the auth/register endpoint with CORS headers
url = "http://localhost:8000/auth/register"
headers = {
    "Origin": "http://localhost:3000",
    "Content-Type": "application/json"
}
data = {
    "email": "cors_test@example.com",
    "password": "TestPassword123!",
    "full_name": "CORS Test User"
}

print("Testing CORS on /auth/register endpoint...")
print(f"Request URL: {url}")
print(f"Origin: {headers['Origin']}")

try:
    # First, test OPTIONS (preflight) request
    print("\n1. Testing OPTIONS (preflight) request...")
    options_response = requests.options(url, headers=headers)
    print(f"   Status: {options_response.status_code}")
    print(f"   CORS Headers: {dict(options_response.headers)}")
    
    # Check if Access-Control-Allow-Origin is present
    if "access-control-allow-origin" in options_response.headers:
        print(f"   ✅ Access-Control-Allow-Origin: {options_response.headers['access-control-allow-origin']}")
    else:
        print("   ❌ Access-Control-Allow-Origin header is MISSING!")
    
    # Now test the actual POST request
    print("\n2. Testing POST request...")
    response = requests.post(url, json=data, headers=headers)
    print(f"   Status: {response.status_code}")
    
    if response.status_code == 200:
        print("   ✅ Registration successful!")
        print(f"   Response: {response.json()}")
    elif response.status_code == 400:
        print(f"   ⚠️  Registration failed (might be duplicate): {response.json()}")
    else:
        print(f"   ❌ Unexpected status: {response.text}")
        
except Exception as e:
    print(f"❌ Error: {e}")

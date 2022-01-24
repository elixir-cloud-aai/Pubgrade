import json
import requests

from mock_data import (
    MOCK_USER_1
)

base_url = "http://192.168.59.100:30008"
headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

user_info = ""
payload_objects = json.dumps(MOCK_USER_1)

def test_post_user():
    """Test `POST /users/register` for successfully creating registering new user."""
    endpoint = "/users/register"
    response = requests.request("POST", base_url + endpoint, headers=headers,
                                data=payload_objects)
    global user_info
    user_info = json.loads(response.content)
    #print(user_info)
    assert response.status_code == 200

def test_error_400_post_user():
    """Test `POST /users/register` for response 400 (Bad request)"""
    endpoint = "/users/register"
    response = requests.request("POST", base_url + endpoint, headers=headers,
                                data={})
    assert response.status_code == 400
    
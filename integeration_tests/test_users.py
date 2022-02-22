import json
import requests
import os
import yaml
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

def set_headers():
    global headers
    with open(os.path.join(os.path.dirname(__file__), '..','..', 'pubgrade', 'config.yaml'), "r") as yamlfile:
        data = yaml.load(yamlfile, Loader=yaml.FullLoader)
        yamlfile.close()
        headers['X-Super-User-Access-Token'] = data['endpoints']['subscriptions']['admin_user']['user_access_token']
        headers['X-Super-User-Id'] = data['endpoints']['subscriptions']['admin_user']['uid']

def test_post_user():
    """Test `POST /users/register` for successfully registering new user."""
    endpoint = "/users/register"
    set_headers()
    response = requests.request("POST", base_url + endpoint, headers=headers,
                                data=payload_objects)
    global user_info
    user_info = json.loads(response.content)
    assert response.status_code == 200
    return user_info

def test_get_users():
    """Test `GET /users` for fetching list of users"""
    endpoint = "/users"
    response = requests.request("GET", base_url + endpoint, headers=headers)
    assert response.status_code == 200

def test_error_400_post_user():
    """Test `POST /users/register` for response 400 (Bad request)"""
    endpoint = "/users/register"
    response = requests.request("POST", base_url + endpoint, headers=headers,
                                data={})
    assert response.status_code == 400

def test_verify_user():
    """Test `PUT /users/{uid}/verify` for verifying user."""
    endpoint = "/users/"+user_info['uid']+"/verify"
    response = requests.request("PUT", base_url + endpoint, headers=headers)
    assert response.status_code == 200

def test_unverify_user():
    """Test `PUT /users/{uid}/verify` for unverifying user."""
    endpoint = "/users/"+user_info['uid']+"/unverify"
    response = requests.request("PUT", base_url + endpoint, headers=headers)
    assert response.status_code == 200









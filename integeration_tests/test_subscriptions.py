import json
import requests

from mock_data import (
    SUBSCRIPTION_PAYLOAD_1
)

from test_users import test_post_user
from test_users import test_verify_user
from test_repositories import test_post_repository

base_url = "http://pubgrade-service-pubgrade.rahtiapp.fi"
headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

user_info = test_post_user()
repo_content = test_post_repository()
SUBSCRIPTION_PAYLOAD_1['repository_id'] = repo_content['id']
SUBSCRIPTION_PAYLOAD_1['access_token'] = repo_content['access_token']
payload_objects = json.dumps(SUBSCRIPTION_PAYLOAD_1)
subscription_id=""
headers['X-User-Access-Token'] = user_info['user_access_token']
headers['X-User-Id'] = user_info['uid']

endpoint = "/users/"+user_info['uid']+"/verify"
response = requests.request("PUT", base_url + endpoint, headers=headers)

def test_post_subscriptions():
    """Test `POST /subscriptions` for successfully creating new subscription"""
    endpoint="/subscriptions"
    response = requests.request("POST", base_url + endpoint, headers=headers,data=payload_objects)
    assert response.status_code == 200
    global subscription_id
    subscription_id = json.loads(response.content)['subscription_id']

def test_error_400_post_subscriptions():
    """Test `POST /subscriptions` for response 400 (Bad request)"""
    endpoint="/subscriptions"
    response = requests.request("POST", base_url + endpoint, headers=headers,data={})
    assert response.status_code == 400

def test_get_subscriptions():
    """Test `GET /subscriptions` for fetching list of subscriptions"""
    endpoint="/subscriptions"
    response = requests.request("GET", base_url + endpoint, headers=headers)
    assert response.status_code == 200

def test_get_subscription():
    """Test `GET /subscriptions/subscriptions_id` for fetching subscription info."""
    endpoint="/subscriptions/"+subscription_id
    response = requests.request("GET", base_url + endpoint, headers=headers)
    assert response.status_code == 200

def test_delete_subscriptions():
    """Test `GET /subscriptions/subscriptions_id` for permanently removing subscription."""
    endpoint="/subscriptions/"+subscription_id
    response = requests.request("DELETE", base_url + endpoint, headers=headers)
    assert response.status_code == 200



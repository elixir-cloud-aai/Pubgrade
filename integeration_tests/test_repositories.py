import json
import requests

from mock_data import (
    MOCK_REPOSITORY_1
)

base_url = "http://192.168.59.100:30008"
headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

reponse_repo = ""
payload_objects = json.dumps(MOCK_REPOSITORY_1)

def test_error_404():
    """Test `GET /` for response 404 (Page not found)"""
    endpoint = "/test_endpoint"
    response = requests.request("GET", base_url + endpoint, headers=headers,
                                data={})
    assert response.status_code == 404

def test_get_repositories():
    """Test `GET /repositories` for fetching repositories."""
    endpoint = "/repositories"
    response = requests.request("GET", base_url + endpoint, headers=headers)
    assert response.status_code == 200

def test_post_repository():
    """Test `POST /repository` for successfully creating or updating a new
    repository.
    """
    endpoint = "/repositories"
    response = requests.request("POST", base_url + endpoint, headers=headers,
                                data=payload_objects)
    global response_repo
    response_repo = json.loads(response.content)
    assert response.status_code == 200
    return response_repo

def test_get_repository():
    """Test `GET /repositories/{id}` for fetching repository info."""
    global response_repo
    endpoint = "/repositories/"+response_repo['id']
    response = requests.request("GET", base_url + endpoint, headers=headers)
    assert response.status_code == 200
    response_content = json.loads(response.content)
    assert response_content['url'] == json.loads(payload_objects)['url']
    assert  response_content != response_repo

def test_put_repository():
    """Test `PUT /repositories/{id}` to modify or update a repository"""
    global response_repo
    endpoint = "/repositories/"+response_repo['id']
    object_put_payload = json.loads(payload_objects)
    object_put_payload['url'] = 'https://github.com/akash2237778/webserver-modified-url'
    headers['X-Project-Access-Token'] = response_repo['access_token']
    response = requests.request("PUT", base_url + endpoint, headers=headers,
                                data=json.dumps(object_put_payload))
    assert response.status_code == 200
    response = requests.request("GET", base_url + endpoint, headers=headers)
    response_content = json.loads(response.content)
    assert response.status_code == 200
    assert response_content['url'] == object_put_payload['url']  

def test_delete_repository():
    """Test `DELETE /repositories/{id}` to delete repository"""
    global response_repo
    endpoint = "/repositories/"+response_repo['id']
    headers['X-Project-Access-Token'] = response_repo['access_token']
    response = requests.request("DELETE", base_url + endpoint, headers=headers)
    assert response.status_code == 200
    assert json.loads(response.content)['message'] == 'Repository deleted successfully'

def test_error_400_post_repository():
    """Test `POST /repositories` for response 400 (Bad request)"""
    endpoint = "/repositories"
    response = requests.request("POST", base_url + endpoint, headers=headers,
                                data={})
    assert response.status_code == 400

def test_error_404_get_repository():
    """Test `GET /repositories/{id}` for response 404 (Resource not found)"""
    endpoint = "/repositories/12"
    response = requests.request("GET", base_url + endpoint, headers=headers)
    assert response.status_code == 404
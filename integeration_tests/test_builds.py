import json
import requests

from mock_data import (
    MOCK_REPOSITORY_1,
    MOCK_BUILD_BODY
)

from test_repositories import test_post_repository

base_url = "http://192.168.59.100:30008"
headers = {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
}

repo_content = test_post_repository()
build_id = ""
payload_objects = json.dumps(MOCK_BUILD_BODY)

def test_get_repository_builds():
    """Test `GET /repositories/{id}/builds` for fetching available builds for repository."""
    global repo_content
    endpoint = "/repositories/"+repo_content['id']+"/builds"
    response = requests.request("GET", base_url + endpoint, headers=headers)
    assert response.status_code == 200

def test_post_build():
    """Test `POST /repositories/{id}/builds` for successfully creating new build."""
    global repo_content
    endpoint = "/repositories/"+repo_content['id']+"/builds"
    headers['X-Project-Access-Token'] = repo_content['access_token']
    response = requests.request("POST", base_url + endpoint, headers=headers,
                                data=payload_objects)
    assert response.status_code == 200
    global build_id
    build_id = json.loads(response.content)['id']
    

def test_get_build():
    """Test `GET /repositories/{id}/builds/{build_id}` for fetching repository build info."""
    global repo_content
    global build_id
    endpoint = "/repositories/"+repo_content['id']+"/builds/"+build_id
    response = requests.request("GET", base_url + endpoint, headers=headers)
    assert response.status_code == 200
    #print(json.loads(response.content))
    assert json.loads(response.content)['images'][0]['name'] == json.loads(payload_objects)['images'][0]['name']

def test_error_400_post_build():
    """Test `POST /repositories/{id}/builds` for response 400 (Bad request)"""
    global repo_content
    endpoint = "/repositories/"+repo_content['id']+"/builds"
    response = requests.request("POST", base_url + endpoint, headers=headers,
                                data={})
    assert response.status_code == 400

"""
def test_put_build():
    #Test `PUT /repositories/{id}/builds/{build_id}` for updating build.
    global repo_content
    global build_id
    endpoint = "/repositories/"+repo_content['id']+"/builds/"+build_id
"""




"""Mock data for testing."""

from typing import Any

INDEX_CONFIG: dict[str, Any] = {"keys": [("id", -1)]}
INDEX_CONFIG_USERS: dict[str, Any] = {"keys": [("uid", -1)]}

COLLECTION_CONFIG: dict[str, Any] = {
    "indexes": [INDEX_CONFIG],
}

COLLECTION_CONFIG_USERS: dict[str, Any] = {
    "indexes": [INDEX_CONFIG_USERS],
}
COLLECTION_CONFIG_ADMIN_USERS: dict[str, Any] = {
    "indexes": [INDEX_CONFIG_USERS],
}

DB_CONFIG: dict[str, Any] = {
    "collections": {
        "repositories": COLLECTION_CONFIG,
        "builds": COLLECTION_CONFIG,
        "subscriptions": COLLECTION_CONFIG,
        "users": COLLECTION_CONFIG_USERS,
        "admin_users": COLLECTION_CONFIG_ADMIN_USERS,
    },
}

MONGO_CONFIG: dict[str, Any] = {
    "host": "mongodb",
    "port": 27017,
    "dbs": {
        "pubgradeStore": DB_CONFIG,
    },
}
ENDPOINT_CONFIG: dict[str, Any] = {
    "repository": {
        "id_charset": ["string.ascii_lowercase", "string.digits", ".", "-"],
        "id_length": 6,
        "retries": 3,
    },
    "user": {
        "uid_charset": ["string.ascii_lowercase", "string.digits", ".", "-"],
        "uid_length": 6,
        "retries": 3,
    },
    "access_token": {
        "charset": ["string.ascii_lowercase", "string.digits", ".", "-"],
        "length": 32,
    },
    "subscriptions": {
        "admin_user": {
            "name": "Akash Saini",
            "uid": "9fe2c4e93f654fdbb24c02b15259716c",
            "user_access_token": "c42a6d44e3d0",
        }
    },
    "builds": {
        "enabled": True,
        "gh_action_path": "akash2237778/pubgrade-signer",
        "intermediate_registery_format": "ttl.sh/{}:1h",
    },
}

MOCK_REPOSITORY_1: dict[str, Any] = {
    "url": "https://github.com/akash2237778/Pubgrade-test",
    "id": "repo12",
    "access_token": "access_token",
}

MOCK_REPOSITORY_2: dict[str, Any] = {
    "url": "https://github.com/akash2237778/Pubgrade-test",
    "id": "eiic.g",
    "access_token": "g.i.ssstitrti.ccier.tgsactt.iosg",
    "build_list": ["eiic.gngdgrs", "eiic.gnabmns"],
    "subscription_list": ["tnglot"],
}
MOCK_REPOSITORIES: list[dict[str, Any]] = [MOCK_REPOSITORY_1, MOCK_REPOSITORY_2]
MOCK_POST_REPOSITORY: dict[str, Any] = {
    "access_token": "xxxxxxxxxxxxxx",
    "id": "repository_123",
}

MOCK_BUILD_INFO: dict[str, Any] = {
    "images": [{"name": "akash7778/test-updater:0.0.1", "location": "./Dockerfile"}],
    "head_commit": {
        "branch": "main",
        "commit_sha": "8cd58eb160014c91e4f181562352c693d3442c52",
    },
    "dockerhub_token": "dXNlcjpwYXNzd2Q=",  # user:passwd  gitleaks:allow
    "id": "eiic.gngdgrs",
    "finished_at": None,
    "started_at": "2021-08-04T17:40:58.344809",
    "status": "QUEUED",
}
MOCK_BUILD_INFO_2: dict[str, Any] = {
    "images": [{"name": "akash7778/updater:0.0.1", "location": "./Dockerfile"}],
    "head_commit": {"tag": "0.4.2"},
    "dockerhub_token": "dockerhub token",
    "id": "eiic.gnabmns",
    "finished_at": None,
    "started_at": "2021-08-04T17:40:58.344809",
    "status": "QUEUED",
}

MOCK_BUILD_PAYLOAD: dict[str, Any] = {
    "images": [{"name": "akash7778/test-updater:0.0.1", "location": "./Dockerfile"}],
    "head_commit": {
        "branch": "main",
        "commit_sha": "8cd58eb160014c91e4f181562352c693d3442c52",
    },
    "dockerhub_token": "dockerhub token",
}

MOCK_SUBSCRIPTION: dict[str, Any] = {"subscription_id": "subscription-xyz"}
MOCK_SUBSCRIPTION_INFO: dict[str, Any] = {
    "repository_id": "eiic.g",
    "callback_url": "https://ec2-54-203-145-132.compute-1.amazonaws.com/update",
    "access_token": "xxxxxxxxxxxx",
    "type": "branch",
    "value": "main",
    "id": "tnglot",
    "state": "Inactive",
}

MOCK_USER: dict[str, Any] = {
    "uid": "9fe2c4e93f654fdbb24c02b15259716c",
    "user_access_token": "c42a6d44e3d0",
    "name": "Akash Saini",
    "isVerified": True,
}

MOCK_ADMIN_USER_1: dict[str, Any] = {
    "uid": "akash.saini",
    "user_access_token": "c42a6d44e3d0",
    "name": "Akash Saini",
}

MOCK_USER_NOT_VERIFIED: dict[str, Any] = {
    "uid": "9fe2c4e93f65424c02b15259716c",
    "user_access_token": "c42a6e3d0",
    "name": "Akash Saini",
    "isVerified": False,
}

MOCK_USER_DB: dict[str, Any] = {
    "uid": "9fe2c4e93f654fdbb24c02b15259716c",
    "name": "Akash Saini",
    "user_access_token": "c42a6d44e3d0",
    "isVerified": True,
    "subscription_list": ["tnglot"],
}
SUBSCRIPTION_PAYLOAD: dict[str, Any] = {
    "repository_id": "eiic.g",
    "callback_url": "https://ec2-54-203-145-132.compute-1.amazonaws.com/update",
    "access_token": "xxxxxxxxxxxx",
    "type": "tag",
    "value": "dev",
    "id": "tnglot",
}
MOCK_ENDPOINT: dict[str, Any] = {
    "repository": {
        "id_charset": "A",
        "id_length": 1,
    }
}

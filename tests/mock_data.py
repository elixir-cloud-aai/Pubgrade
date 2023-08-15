"""Mock data for testing"""

INDEX_CONFIG = {"keys": [("id", -1)]}
INDEX_CONFIG_USERS = {"keys": [("uid", -1)]}

COLLECTION_CONFIG = {
    "indexes": [INDEX_CONFIG],
}

COLLECTION_CONFIG_USERS = {
    "indexes": [INDEX_CONFIG_USERS],
}
COLLECTION_CONFIG_ADMIN_USERS = {
    "indexes": [INDEX_CONFIG_USERS],
}

DB_CONFIG = {
    "collections": {
        "repositories": COLLECTION_CONFIG,
        "builds": COLLECTION_CONFIG,
        "subscriptions": COLLECTION_CONFIG,
        "users": COLLECTION_CONFIG_USERS,
        "admin_users": COLLECTION_CONFIG_ADMIN_USERS,
    },
}

MONGO_CONFIG = {
    "host": "mongodb",
    "port": 27017,
    "dbs": {
        "pubgradeStore": DB_CONFIG,
    },
}
ENDPOINT_CONFIG = {
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
            "gh_action_path": "akash2237778/pubgrade-signer",
            "intermediate_registery_format": "ttl.sh/{}:1h"
        },
}

MOCK_REPOSITORY_1 = {
    "url": "https://github.com/akash2237778/Pubgrade-test",
    "id": "repo_123",
    "access_token": "access_token",
}
MOCK_REPOSITORY_1 = {
    "url": "https://github.com/akash2237778/Pubgrade-test",
    "id": "repo12",
    "access_token": "access_token",
}

MOCK_REPOSITORY_2 = {
    "url": "https://github.com/akash2237778/Pubgrade-test",
    "id": "eiic.g",
    "access_token": "g.i.ssstitrti.ccier.tgsactt.iosg",
    "build_list": ["eiic.gngdgrs", "eiic.gnabmns"],
    "subscription_list": ["tnglot"],
}
MOCK_REPOSITORIES = [MOCK_REPOSITORY_1, MOCK_REPOSITORY_2]
MOCK_POST_REPOSITORY = {
    "access_token": "xxxxxxxxxxxxxx",
    "id": "repository_123",
}

MOCK_BUILD_INFO = {
    "images": [
        {"name": "akash7778/test-updater:0.0.1", "location": "./Dockerfile"}
    ],
    "head_commit": {
        "branch": "main",
        "commit_sha": "8cd58eb160014c91e4f181562352" "c693d3442c52",
    },
    "dockerhub_token": "dXNlcjpwYXNzd2Q=",
    "id": "eiic.gngdgrs",
    "finished_at": "NULL",
    "started_at": "2021-08-04T17:40:58.344809",
    "status": "QUEUED",
}
MOCK_BUILD_INFO_2 = {
    "images": [
        {"name": "akash7778/updater:0.0.1", "location": "./Dockerfile"}
    ],
    "head_commit": {"tag": "0.4.2"},
    "dockerhub_token": "dockerhub token",
    "id": "eiic.gnabmns",
    "finished_at": "NULL",
    "started_at": "2021-08-04T17:40:58.344809",
    "status": "QUEUED",
}

MOCK_BUILD_PAYLOAD = {
    "images": [
        {"name": "akash7778/test-updater:0.0.1", "location": "./Dockerfile"}
    ],
    "head_commit": {
        "branch": "main",
        "commit_sha": "8cd58eb160014c91e4f181562352c693d3442c52",
    },
    "dockerhub_token": "dockerhub token",
}

MOCK_SUBSCRIPTION = {"subscription_id": "subscription-xyz"}
MOCK_SUBSCRIPTION_INFO = {
    "repository_id": "eiic.g",
    "callback_url": "https://ec2-54-203-145-132."
    "compute-1.amazonaws.com/update",
    "access_token": "xxxxxxxxxxxx",
    "type": "branch",
    "value": "main",
    "id": "tnglot",
    "state": "Inactive",
}

MOCK_USER = {
    "uid": "9fe2c4e93f654fdbb24c02b15259716c",
    "user_access_token": "c42a6d44e3d0",
    "name": "Akash Saini",
    "isVerified": True,
}

MOCK_ADMIN_USER_1 = {
    "uid": "akash.saini",
    "user_access_token": "c42a6d44e3d0",
    "name": "Akash Saini",
}

MOCK_USER_NOT_VERIFIED = {
    "uid": "9fe2c4e93f65424c02b15259716c",
    "user_access_token": "c42a6e3d0",
    "name": "Akash Saini",
    "isVerified": False,
}

MOCK_USER_DB = {
    "uid": "9fe2c4e93f654fdbb24c02b15259716c",
    "name": "Akash Saini",
    "user_access_token": "c42a6d44e3d0",
    "isVerified": True,
    "subscription_list": ["tnglot"],
}
SUBSCRIPTION_PAYLOAD = {
    "repository_id": "eiic.g",
    "callback_url": "https://ec2-54-203-145-132."
    "compute-1.amazonaws.com/update",
    "access_token": "xxxxxxxxxxxx",
    "type": "tag",
    "value": "dev",
    "id": "tnglot",
}
MOCK_ENDPOINT = {
    "repository": {
        "id_charset": "A",
        "id_length": 1,
    }
}

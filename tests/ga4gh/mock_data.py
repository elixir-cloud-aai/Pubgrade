"""Mock data for testing"""

INDEX_CONFIG = {
    'keys': [('id', -1)]
}
INDEX_CONFIG_USERS = {
    'keys': [('uid', -1)]
}

COLLECTION_CONFIG = {
    'indexes': [INDEX_CONFIG],
}

COLLECTION_CONFIG_USERS = {
    'indexes': [INDEX_CONFIG_USERS],
}

DB_CONFIG = {
    'collections': {
        'repositories': COLLECTION_CONFIG,
        'builds': COLLECTION_CONFIG,
        'subscriptions': COLLECTION_CONFIG,
        'users': COLLECTION_CONFIG_USERS
    },
}

MONGO_CONFIG = {
    'host': 'mongodb',
    'port': 27017,
    'dbs': {
        'brokerStore': DB_CONFIG,
    },
}
ENDPOINT_CONFIG = {
    "repository": {
        "id_charset": [
            "string.ascii_lowercase",
            "string.digits",
            ".",
            "-"
        ],
        "id_length": 6
    }
}


MOCK_REPOSITORY = {
   "url": "https://localhost:8080/repositories",
   "id": "repo_123"
}
MOCK_POST_REPOSITORY = {
   "access_token": "xxxxxxxxxxxxxx",
   "id": "repository_123"
}

MOCK_BUILD_INFO = {
   "images": [
      {
         "name": "akash7778/broker:0.0.1",
         "location": "./Dockerfile"
      },
      {
         "name": "akash7778/broker:0.0.1",
         "location": "./Dockerfile"
      }
   ],
   "head_commit": {
      "branch": "development",
      "commit_sha": "930fd5"
   },
   "status": "UNKNOWN",
   "started_at": "2021-06-11T17:32:28Z",
   "finished_at": "2021-06-11T17:32:28Z"
}

MOCK_SUBSCRIPTION = {
   "subscription_id": "subscription-xyz"
}
MOCK_SUBSCRIPTION_INFO = {
   "callback_url": "https://ec2-54-203-145-132.compute-1.amazonaws.com/update",
   "repository_id": "respository123",
   "build_id": "build_123",
   "build_type": "production",
   "state": "Active",
   "updated_at": "2021-06-11T17:32:28+00:00"
}

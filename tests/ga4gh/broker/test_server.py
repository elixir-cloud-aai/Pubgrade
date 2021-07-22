import mongomock

from flask import Flask

from foca.models.config import Config
from foca.models.config import MongoConfig

from broker.ga4gh.broker.server import (
    postRepositories
)

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


def test_postRepositories():
    """Test for creating a new repository with an auto-generated
    identifier."""
    app = Flask(__name__)
    app.config['FOCA'] = \
        Config(db=MongoConfig(**MONGO_CONFIG), endpoints=ENDPOINT_CONFIG)
    app.config['FOCA'].db.dbs['brokerStore']. \
        collections['repositories'].client = mongomock.MongoClient(

    ).db.collection
    with app.test_request_context(
            json={"url": "https://github.com/elixir-cloud-aai/drs-filer.git"}):
        res = postRepositories.__wrapped__()
        assert isinstance(res, dict)

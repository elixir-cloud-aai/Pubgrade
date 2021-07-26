import mongomock

from flask import Flask

from foca.models.config import Config
from foca.models.config import MongoConfig

from broker.ga4gh.broker.server import (
    postRepositories
)

from tests.ga4gh.mock_data import (
        MONGO_CONFIG,
        ENDPOINT_CONFIG
)


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

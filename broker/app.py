"""Main app module."""

import logging

from flask import current_app
from foca.foca import foca

logger = logging.getLogger(__name__)

uid = "9fe2c4e93f654fdbb24c02b15259716c"
name = "Akash"
user_access_token = "c42a6d44e3d0"


def test_create_user(app):
    """
    Right now this function is used to create user and will be deleted later.
    """
    with app.app.app_context():
        db_collection = (
            current_app.config['FOCA'].db.dbs['brokerStore'].
            collections['users'].client
        )
        data = db_collection.find({"uid": uid})
        if data.count() == 0:
            db_collection.insert_one({
                'uid': uid,
                'name': name,
                'user_access_token': user_access_token
            })


def main():
    app = foca("config.yaml")
    test_create_user(app)
    app.run(port=app.port)


if __name__ == '__main__':
    main()

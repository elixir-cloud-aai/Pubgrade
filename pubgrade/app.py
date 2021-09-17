"""Main app module."""

import logging

from flask import current_app
from foca.foca import foca

logger = logging.getLogger(__name__)


def test_create_user(app):
    """
    Function is used to create admin user.
    """
    with app.app.app_context():
        uid = current_app.config['FOCA'].endpoints['subscriptions'][
            'admin_user']['uid']
        name = current_app.config['FOCA'].endpoints['subscriptions'][
            'admin_user']['name']
        user_access_token = current_app.config[
            'FOCA'].endpoints['subscriptions'][
            'admin_user']['user_access_token']
        db_collection = (
            current_app.config['FOCA'].db.dbs['pubgradeStore'].
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

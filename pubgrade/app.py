"""Main app module."""

import logging

from flask import current_app
from foca.foca import foca

logger = logging.getLogger(__name__)


def create_admin_user(app):
    """
    Function is used to create admin user.
    """
    with app.app.app_context():

        # Adding admin users from `config.yaml`.
        admin_users = current_app.config["FOCA"].endpoints["subscriptions"][
            "admin_users"
        ]
        for user in admin_users:
            uid = user["uid"]
            name = user["name"]
            user_access_token = user["user_access_token"]
            db_collection = (
                current_app.config["FOCA"]
                .db.dbs["pubgradeStore"]
                .collections["admin_users"]
                .client
            )
            data = db_collection.find({"uid": uid})
            if data.count() == 0:
                db_collection.insert_one(
                    {
                        "uid": uid,
                        "name": name,
                        "user_access_token": user_access_token,
                    }
                )


def main():
    app = foca("config.yaml")
    create_admin_user(app)
    app.run(port=app.port)


if __name__ == "__main__":
    main()

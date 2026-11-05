"""Main app module."""

import logging

from flask import current_app
from foca.foca import foca

logger = logging.getLogger(__name__)


def create_admin_user(app):
    """Make the admin users in the database match the configuration.

    New tokens take effect at the next start, and users removed from the
    configuration lose their rights.

    Args:
        app: The app, as returned by FOCA.
    """
    with app.app.app_context():
        admin_users = current_app.config["FOCA"].endpoints["subscriptions"][
            "admin_users"
        ]
        db_collection = (
            current_app.config["FOCA"]
            .db.dbs["pubgradeStore"]
            .collections["admin_users"]
            .client
        )
        for user in admin_users:
            db_collection.replace_one(
                {"uid": user["uid"]},
                {
                    "uid": user["uid"],
                    "name": user["name"],
                    "user_access_token": user["user_access_token"],
                },
                upsert=True,
            )
        db_collection.delete_many(
            {"uid": {"$nin": [user["uid"] for user in admin_users]}}
        )


def main():
    app = foca("config.yaml")
    create_admin_user(app)
    app.run(port=app.port)


if __name__ == "__main__":
    main()

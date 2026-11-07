"""App factory, and entry point for development.

The image serves the app with Gunicorn (`pubgrade.app:create_app()`, with
FOCA's settings, `foca.gunicorn_config`); `python -m pubgrade.app` runs it
with Flask's development server.
"""

import logging
from pathlib import Path

from connexion import App
from foca import Foca, get_collection, get_config

from pubgrade.charsets import check_charsets
from pubgrade.timestamps import repair_timestamps

logger = logging.getLogger(__name__)

# The configuration of the app, independent of the working directory;
# deployments mount their own copy over it
CONFIG_FILE = Path(__file__).resolve().parent / "config.yaml"
DB = "pubgradeStore"


def create_admin_user(app: App) -> None:
    """Make the admin users in the database match the configuration.

    New tokens take effect at the next start, and users removed from the
    configuration lose their rights.

    Args:
        app: The app, as returned by FOCA.
    """
    with app.app.app_context():
        admin_users = get_config().endpoints["subscriptions"]["admin_users"]
        db_collection = get_collection(DB, "admin_users")
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


def create_app() -> App:
    """Create the app from its configuration, with the admin users.

    Gunicorn calls this in each worker, after forking (MongoDB clients must
    not be shared across forks). Also brings stored timestamps into the
    format of the API (cf. `repair_timestamps()`). Stops with an error if a
    character set setting can't be used (cf. `check_charsets()`).

    Returns:
        Connexion app.
    """
    app = Foca(config_file=CONFIG_FILE).create_app()
    with app.app.app_context():
        check_charsets(get_config().endpoints)
    create_admin_user(app)
    with app.app.app_context():
        repair_timestamps(
            get_collection(DB, "builds"), get_collection(DB, "subscriptions")
        )
    return app


def main() -> None:
    """Run the app with Flask's development server, on the configured port.

    For development; not for production.
    """
    app = create_app()
    app.run(port=app.port)


if __name__ == "__main__":
    main()  # pragma: no cover

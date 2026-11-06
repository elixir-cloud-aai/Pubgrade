"""Gunicorn settings of the image: FOCA's, with more threads and shutdown time.

A publish holds its thread until the subscribers answer (up to twice
`notification_timeout`, plus 5 seconds), and so does a slow client while it
sends its request; hence 16 threads instead of FOCA's 4. On shutdown,
Gunicorn waits `graceful_timeout` for running requests, so that a publish
can finish within Kubernetes' default grace period of 30 seconds.
`GUNICORN_CMD_ARGS` overrides these settings.
"""

from foca.gunicorn_config import *  # noqa: F401,F403

threads = 16
graceful_timeout = 28

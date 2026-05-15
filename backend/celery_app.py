import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

app = Celery(
    "store_scraper",
    broker=REDIS_URL,
    backend=REDIS_URL,
)

app.conf.task_serializer = "json"
app.conf.result_serializer = "json"
app.conf.accept_content = ["json"]

import tasks  # noqa: F401 — register tasks so the worker can discover them

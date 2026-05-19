# tasks.py - Celery task for scraping store products and logging progress to Redis

import json
import os
import redis
from celery_app import app
from scraper import scrape_store_products
from db import ensure_table, save_result


@app.task(bind=True)
def run_scrape(self, store_name: str):
    r = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    log_key = f"task:{self.request.id}:logs"

    def log(msg):
        r.rpush(log_key, json.dumps({"type": "log", "message": msg}))
        r.expire(log_key, 300)

    ensure_table()

    try:
        log("Initializing Chrome driver...")
        result = scrape_store_products(store_name, log_callback=log)
        log(f"Scraping complete. Found {result['product_count']} products.")
        save_result(
            store_name=store_name,
            product_count=result["product_count"],
            products=result["products"],
        )
        r.rpush(log_key, json.dumps({
            "type": "complete",
            "result": result,
            "task_id": self.request.id,
        }))
        r.expire(log_key, 300)
        return result
    except Exception as e:
        error_msg = f"Task failed: {str(e)}"
        r.rpush(log_key, json.dumps({"type": "error", "message": error_msg}))
        r.expire(log_key, 300)
        raise

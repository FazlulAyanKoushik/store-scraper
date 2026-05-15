import json
import os
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from db import ensure_table, get_history
from tasks import run_scrape
from celery.result import AsyncResult
from celery_app import app as celery_app
import redis.asyncio as aioredis

app = FastAPI(title="Store Product Scraper API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    ensure_table()


class ScrapeRequest(BaseModel):
    store_name: str


@app.post("/api/scrape")
async def scrape(request: ScrapeRequest):
    if not request.store_name.strip():
        raise HTTPException(status_code=400, detail="store_name is required")

    task = run_scrape.delay(request.store_name.strip())
    return {"task_id": task.id}


@app.get("/api/task/{task_id}")
async def task_status(task_id: str):
    task = AsyncResult(task_id, app=celery_app)
    if task.ready():
        if task.successful():
            return {"status": "SUCCESS", "result": task.result}
        else:
            return {"status": "FAILURE", "error": str(task.info)}
    return {"status": "PENDING"}


@app.websocket("/api/ws/{task_id}")
async def task_logs(websocket: WebSocket, task_id: str):
    await websocket.accept()
    r = aioredis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    log_key = f"task:{task_id}:logs"
    try:
        existing = await r.lrange(log_key, 0, -1)
        for item in existing:
            payload = json.loads(item)
            await websocket.send_json(payload)
            if payload.get("type") == "complete":
                return

        while True:
            result = await r.blpop(log_key, timeout=30.0)
            if result is None:
                await websocket.send_json({
                    "type": "log",
                    "message": "[Connection timeout — no log updates]",
                })
                break
            _, data = result
            payload = json.loads(data)
            await websocket.send_json(payload)
            if payload.get("type") in ("complete", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        await r.close()


@app.get("/api/history/{store_name}")
async def history(store_name: str):
    items = get_history(store_name)
    return {"store_name": store_name, "history": items}


@app.get("/health")
def health():
    return {"status": "ok"}

# Store Product Scraper

A web application that scrapes Google search results (Japanese locale) to find and count products listed for a given store name. Uses **Celery** for async task processing and **WebSocket** for real-time log streaming to the frontend.

## Architecture

```
┌──────────────┐   ┌──────────────┐   ┌─────────────┐   ┌───────────┐
│   Frontend   │   │   FastAPI    │   │   Redis     │   │ Celery    │
│  (React/Vite)│◄──│  Backend     │◄──│  (Broker)   │──►│  Worker   │
│  Port: 5173  │   │  Port: 8000  │   │  Port: 6379 │   │  +Selenium│
└──────┬───────┘   └──────┬───────┘   └─────────────┘   └─────┬─────┘
       │  WebSocket       │                                    │
       └── real-time logs ┘                          ┌─────────▼──────┐
                                                     │   DynamoDB    │
                                                     │   (Local)     │
                                                     │   Port: 8001  │
                                                     └───────────────┘
```

## Quick Start

```bash
cd store-scraper
docker compose up --build
```

| Service        | URL                          |
|----------------|------------------------------|
| Frontend       | http://localhost:5173        |
| Backend API    | http://localhost:8000/docs   |
| DynamoDB       | http://localhost:8001        |

## Project Structure

```
store-scraper/
├── docker-compose.yml          # Orchestrates all services
├── backend/
│   ├── Dockerfile              # Python 3.11 + Chromium
│   ├── requirements.txt
│   ├── main.py                 # FastAPI entry point + WebSocket handler
│   ├── celery_app.py           # Celery app configuration
│   ├── tasks.py                # Celery async scraping task
│   ├── scraper.py              # Selenium scraping logic (with log callbacks)
│   └── db.py                   # DynamoDB client & operations
├── frontend/
│   ├── Dockerfile              # Node 20 + Vite
│   ├── package.json
│   ├── vite.config.js
│   ├── index.html
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       └── components/
│           ├── SearchForm.jsx
│           ├── LogPanel.jsx    # Real-time log viewer
│           └── ResultCard.jsx
├── dynamodb/
│   └── init-table.sh           # Optional table initializer
└── README.md
```

## API

### `POST /api/scrape`

Submit a scraping task. Returns a `task_id` immediately (non-blocking).

```bash
curl -X POST http://localhost:8000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"store_name": "美匠"}'
```

Response: `{"task_id": "..."}`

### `WS /api/ws/{task_id}`

WebSocket endpoint for live log streaming while a task is running. The server pushes JSON messages:

- `{"type": "log", "message": "..."}` — progress update
- `{"type": "complete", "result": {...}}` — scraping finished with result
- `{"type": "error", "message": "..."}` — task failed

### `GET /api/task/{task_id}`

Poll task status and result.

```bash
curl http://localhost:8000/api/task/<task_id>
```

### `GET /api/history/{store_name}`

Retrieve past scrape results for a store.

```bash
curl http://localhost:8000/api/history/%E7%BE%8E%E5%8C%A0
```

### `GET /health`

Health check.

## How It Works

1. User enters a store name in the React frontend → clicks Search.
2. FastAPI immediately returns a `task_id` and dispatches a **Celery** task.
3. Frontend opens a **WebSocket** to `/api/ws/{task_id}` for live logs.
4. **Celery worker** runs Selenium Chrome headlessly:
   - Opens Google with Japanese locale (`hl=ja&gl=jp`).
   - Finds the merchandise section and clicks "Show all" (すべて表示).
   - Extracts product names from the modal.
   - Publishes each step as a log message to **Redis**.
5. FastAPI streams log messages from Redis to the frontend WebSocket in real time.
6. When complete, the result (product count + list) is saved to **DynamoDB** and sent to the frontend.

## Tech Stack

| Layer          | Technology                            |
|----------------|---------------------------------------|
| Frontend       | React 18 + Vite                       |
| Backend API    | FastAPI + Uvicorn                     |
| Task Queue     | Celery + Redis (broker & result backend) |
| Scraping       | Selenium 4 + Chromium (headless)      |
| Database       | DynamoDB Local (Docker)               |
| Real-time      | WebSocket + Redis list (BLPOP streaming) |
| Container      | Docker Compose                        |

## Known Issues

- Google's DOM structure changes frequently — XPath selectors may need periodic updates.
- The products section only reliably appears with the Japanese locale (`hl=ja&gl=jp`).
- CJK fonts are bundled (`fonts-noto-cjk`) to prevent box rendering in Chromium.
- Chrome requires `shm_size: "2gb"` in Docker to avoid crashes.

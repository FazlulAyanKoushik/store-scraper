# POC: Google Store Product Scraper — Instruction Manual

## Project Overview

A web application where a user inputs a store name (e.g., `美匠`), the backend scrapes the Google search results page (Japanese locale) to find the **merchandise/products section**, clicks "Show all", and returns the **total product count** for that store. All results are persisted in DynamoDB (running in Docker).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     Docker Compose                      │
│                                                         │
│  ┌──────────────┐   ┌──────────────┐   ┌─────────────┐ │
│  │   Frontend   │   │   FastAPI    │   │  DynamoDB   │ │
│  │  (React/Vite)│◄──│  Backend     │──►│  (Local)    │ │
│  │  Port: 5173  │   │  Port: 8000  │   │  Port: 8001 │ │
│  └──────────────┘   └──────┬───────┘   └─────────────┘ │
│                             │                           │
│                      ┌──────▼───────┐                   │
│                      │  Selenium    │                   │
│                      │  Chrome +    │                   │
│                      │  ChromeDriver│                   │
│                      └──────────────┘                   │
└─────────────────────────────────────────────────────────┘
```

---

## Project Directory Structure

```
store-scraper/
├── docker-compose.yml
├── instruction.md
│
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                  # FastAPI app entry point
│   ├── scraper.py               # Selenium scraping logic
│   └── db.py                    # DynamoDB client & operations
│
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       └── components/
│           ├── SearchForm.jsx
│           └── ResultCard.jsx
│
└── dynamodb/
    └── init-table.sh            # Optional: pre-create tables on startup
```

---



> **Important scraping note**: Google's DOM structure changes frequently. The XPath selectors above cover known patterns as of mid-2025. Expect to update selectors periodically. Use `driver.page_source` to debug when selectors fail.

---

### Running the Project

```bash
# Clone or create the directory structure, then:
cd store-scraper

# Build and start all services
docker compose up --build

# Access:
# Frontend:  http://localhost:5173
# Backend:   http://localhost:8000/docs  (Swagger UI)
# DynamoDB:  http://localhost:8001
```

---

### Known Issues & Debugging Guide

#### Issue 1: Products section not visible
**Cause**: Google only shows the merchandise/products section when using the Japanese locale.
**Fix**: The scraper uses `?hl=ja&gl=jp` and `--lang=ja` Chrome flag. If still missing, try `https://www.google.co.jp/search?q=...&hl=ja` instead.

#### Issue 2: Selenium XPath selectors fail
**Cause**: Google updates its DOM structure frequently.
**Debug**: Add this to `scraper.py` to dump page source:
```python
with open("/tmp/debug_page.html", "w") as f:
    f.write(driver.page_source)
```
Then:
```bash
docker exec -it fastapi-backend cat /tmp/debug_page.html | grep -i "product"
```

#### Issue 3: Chrome crashes inside Docker
**Fix**: Ensure `shm_size: "2gb"` is in `docker-compose.yml` under the backend service. Also add:
```
--disable-dev-shm-usage
--no-sandbox
```
These are already included in the scraper, but confirm they're present.


#### Issue 5: CJK characters render as boxes in Chrome
**Fix**: The Dockerfile installs `fonts-noto-cjk`. If still broken, also install `fonts-ipafont`.

---

### 6. DynamoDB Schema

| Attribute | Type | Role |
|-----------|------|------|
| `store_name` | String | Partition Key |
| `scraped_at` | String (ISO datetime) | Sort Key |
| `product_count` | Number | Product count |
| `products` | List\<String\> | Product names |

---

### 7. Testing the API Manually

```bash
# Health check
curl http://localhost:8000/health

# Scrape a store
curl -X POST http://localhost:8000/api/scrape \
  -H "Content-Type: application/json" \
  -d '{"store_name": "美匠"}'

# Get scrape history
curl http://localhost:8000/api/history/%E7%BE%8E%E5%8C%A0
```

---

### 8. Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 + Vite |
| Backend API | FastAPI + Uvicorn |
| Scraping | Selenium 4 + Chromium (headless) |
| Database | DynamoDB Local (Docker) |
| Containerization | Docker Compose |
| Language | Python 3.11 / JavaScript (ESM) |

---

### 9. Extension Ideas (Post-POC)

- Add a **scheduler** (APScheduler or Celery) to re-scrape stores on a schedule
- Store **screenshots** of the product modal in S3 for audit/debugging
- Add a **history table** in the UI to compare product counts over time
- Replace DynamoDB Local with **AWS DynamoDB** by swapping the endpoint URL env var
- Add **proxy rotation** if Google blocks the scraper IP

---

*End of instruction.md*
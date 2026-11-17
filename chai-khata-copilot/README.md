# Chai Khata Copilot — Speak. Manage. Grow.
Voice-first business copilot for chaiwalas: udhaar ledger, sales, expenses, inventory prediction, insights, bill review, daily report.

## Architecture
- `backend/` FastAPI + SQLite (money as integer paise, FK + CHECK constraints, per-shop isolation via `shop_id`)
- `nlu.py` Hindi/Hinglish/English parser (rules; optional LLM via `ANTHROPIC_API_KEY`, validated, falls back to rules)
- `tools.py` deterministic tools: credit, payment, sale, expense, stock, predict, insights, dashboard. The parser/LLM never writes to the DB.
- Flow: `/api/voice` parses and stores a *pending* action list -> user confirms -> `/api/confirm` executes in one DB transaction with idempotency keys and audit log.
- `frontend/index.html` single-page UI served at `/` (mic via browser Web Speech API, text fallback).

## Run
```
cd backend
pip install -r requirements.txt
uvicorn main:app --reload      # open http://localhost:8000
python -m pytest -q            # 5 tests
```
Env vars: see `.env.example`. Press "Demo data" on the login page for a separate demo shop (10 customers, 30 days of sales/expenses); pressing it again resets it.

## API (all except login/register/demo need `Authorization: Bearer <token>`)
| Endpoint | Purpose |
|---|---|
| POST /api/register, /api/login, /api/demo | get a session token |
| POST /api/voice `{text}` | parse; balance questions answered at once, writes return a `pending_id` |
| POST /api/confirm, /api/cancel `{pending_id}` | execute or drop a pending action (idempotent) |
| GET /api/dashboard, /customers, /inventory | today's numbers, insights, tomorrow's estimate, balances, stock |
| GET /api/reminder/{id} | draft WhatsApp reminder (never sent automatically) |
| POST /api/bill/parse, /bill/confirm `{text,supplier}` | review bill text, then update stock and expenses; duplicate bills rejected |

## Known limitations (honest list)
- Not production-hardened: simple bearer sessions (no expiry/refresh), in-memory rate limiter, SQLite, no HTTPS or row-level DB security.
- Voice recognition is the browser's (Chrome); it needs internet. Languages: Hindi, English, Hinglish only (no Kannada/Marathi).
- No offline queue/sync yet: the app needs the server. Chat is single-command with one memory: the last customer (so "usne 100 de diye" works). No longer conversations.
- Bill scanner takes pasted/OCR text only: no camera or OCR is bundled, and no price-increase comparison.
- LLM parsing path is written but untested (no API key was available). Rule parser is what the tests cover.
- Profit uses product costs assumed in `nlu.PROD`, and stock usage per cup assumed in `tools.USE`. Both are estimates. Predictions are a same-weekday average, not a forecast model.
- Not built: customer credit limits, overdue alerts, suppliers table, order queue, PDF export, message sharing, UI for customer phone edit.

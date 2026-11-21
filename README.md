# Chai Khata Copilot — Speak. Manage. Grow.
Voice-first business copilot for chaiwalas: udhaar ledger, sales, expenses, inventory prediction, insights, bill review, daily report.

## Table of contents
1. [The problem](#the-problem)
2. [Features](#features)
3. [How it works](#how-it-works)
4. [Tech stack](#tech-stack)
5. [Run](#run)
6. [API Reference](#api-reference)



## The problem
Small chai stalls run on ₹10 cups and a paper notebook:
- **Udhaar lives on paper.** Entries get lost, forgotten or disputed.
- **Hands are always busy.** There is no time to type, so sales and expenses go unrecorded.
- **Profit is a guess.** The owner sees cash in the drawer, not what the day actually earned.
- **Apps do not speak his language.** Most business apps are English-only with complex forms.

## Features

| Feature | What id does |
|---|---|
| **Voice & Text Entry** | Speak or type in Hindi, English or Hinglish. |
|  **One-Tap Sales** | Instantly record product sales with an Undo option. |
| **Udhaar Ledger** | Track customer credit, repayments and outstanding balances. |
| **Smart Name Matching** | Recognizes names across English and Devanagari scripts. |
| **Sales & Profit** | Dashboard with sales, cash/UPI, expenses and estimated profit. |
| **Inventory Prediction** | Track stock and estimate tomorrow's requirements. |
| **Business Insights** | Weekly sales trends, profitable products and peak hours. |
| **Bill Review** | Review supplier bills before updating stock and expenses. |
| **Shop Settings** | Manage products, prices, costs and owner information. |
| **WhatsApp Reports** | Daily 9 PM business summary for the shop owner. |
| **Bilingual Interface** | Complete English and Hindi interface. |
| **Demo Mode** | Explore a separate demo shop with 10 customers and 30 days of sample data. |

## How it works

```
speak / type  ->  /api/voice  ->  parser proposes actions  ->  pending (nothing saved yet)
                                                                  |
                         owner confirms  ->  /api/confirm  ->  one DB transaction + audit log
```

- **The parser never writes to the database.** `/api/voice` only stores a *pending* action list. Only `/api/confirm` executes it, in a single transaction, with idempotency keys. A misheard word cannot corrupt the books.
- Balance questions ("Ramesh ka kitna baaki hai?") are answered immediately.
- Small sales can auto-save with an Undo link; one-tap buttons save instantly.
- The parser remembers the **last customer**, so "usne 100 de diye" works.
- Money is stored as **integer paise** (no floating-point rounding errors), with foreign keys and CHECK constraints. Every shop's data is isolated by `shop_id`.

## Tech stack
- **Frontend:** a single HTML/CSS/JavaScript page (`frontend/index.html`), served by the backend. Browser Web Speech API for mic and spoken replies.
- **Backend:** Python, FastAPI, Uvicorn.
- **Database:** SQLite.
- **Language understanding:** rule-based Hindi/Hinglish/English parser; optional LLM path (Anthropic API) that is validated and falls back to the rules on any error.
- **Messaging:** Twilio WhatsApp API (daily summary), `wa.me` links (reminders and manual send).
- **Security:** PBKDF2-SHA256 password hashing, per-shop bearer sessions, in-memory rate limiter, audit log.
- **Tests:** pytest.


## Run

```
Requirements: Python 3.10+ and Chrome (for the mic).

```bash
cd backend
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Open **http://localhost:8000**, then either register a shop or press **Demo data** on the login page to explore with sample data.

##  API Reference

All endpoints except registration, login and demo require:

```http
Authorization: Bearer <token>
```

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/register` | Register a shop |
| POST | `/api/login` | Owner login |
| POST | `/api/demo` | Access demo shop |
| GET / PUT | `/api/settings` | Manage settings |
| GET / POST | `/api/products` | View and add products |
| PUT / DELETE | `/api/products/{id}` | Edit and remove products |
| PUT | `/api/customers/{id}` | Edit customer details |
| POST | `/api/voice` | Process voice or text commands |
| POST | `/api/confirm` | Confirm pending actions |
| POST | `/api/cancel` | Cancel pending actions |
| POST | `/api/quick` | Record instant sales |
| POST | `/api/undo-sale/{id}` | Undo a sale |
| GET | `/api/dashboard` | View business dashboard |
| GET | `/api/customers` | View customer balances |
| GET | `/api/inventory` | View stock |
| GET | `/api/reminder/{id}` | Generate WhatsApp reminder |
| POST | `/api/bill/parse` | Parse supplier bills |
| POST | `/api/bill/confirm` | Confirm supplier bills |
| GET | `/api/sales/daily?days=7` | View daily product-wise sales |


Built by (Sanchitha Poojari).
Built as part of the OffCampus Code initiative.
OffCampus Code : UDD2HM



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
python -m pytest -q            # 17 tests
```
Env vars: see `.env.example`. Press "Demo data" on the login page for a separate demo shop (10 customers, 30 days of sales/expenses); pressing it again resets it.

## API (all except login/register/demo need `Authorization: Bearer <token>`)
| Endpoint | Purpose |
|---|---|
| POST /api/register, /api/login, /api/demo | get a session token |
| GET/PUT /api/settings, /settings/shop · POST /settings/password, /settings/test-message | shop & owner info, daily-message switch, password, send a test message |
| GET/POST /api/products · PUT/DELETE /api/products/{id} | add, edit, remove products (price, cost, Hindi name, spoken words) |
| PUT /api/customers/{id} `{name,phone}` | edit an udhaar customer's name and phone |
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
- Not built: customer credit limits, overdue alerts, suppliers table, order queue, PDF export, deleting customers.
- Stock usage per cup (`tools.USE`) is still fixed in code; Settings edits the products you sell, not the stock items.

## Fast sale entry (no need to say every cup)
- **One tap:** one big button per product records a sale instantly with an Undo link. A client key makes double taps harmless. The buttons come from your product list (Settings).
- API: `POST /api/quick`, `POST /api/undo-sale/{id}`.
- The old "day total" shortcut was removed. Old "Manual total" rows already in a database are kept and still show in reports, but nothing creates new ones.

## Settings tab
- **Shop and owner:** shop name, owner name, phone, address. Changing the phone number (it is also the login) asks for the current password. Password can be changed separately.
- **Products:** add, edit, remove. Each has a price, a cost (used for profit), an optional Hindi name and extra words you can say ("samose"). Editing a price affects new sales only. Renaming a product renames it in past sales too. Removing hides it (no tap button, no voice match) but keeps past sales.
- **Udhaar customers:** in the Credit tab, *Edit* changes a customer's name and phone (the phone is used for the WhatsApp reminder).

## Daily 9 PM message (WhatsApp, to the owner himself)
Every day from 9:00 PM (`NOTIFY_HOUR`, shop-local time, `TZ` default `Asia/Kolkata`) each shop's summary goes to the **owner's own WhatsApp number** (the phone number in Settings): sales (cups, cash/UPI), expenses, estimated profit, best seller and credit pending, in the language chosen in Settings. It is sent once per day (restarts and extra workers do not duplicate it; a server that was down at 9 PM still sends later that evening; failures retry up to 3 times, 10 minutes apart). Demo shops are never messaged. Switch it off in Settings.
- **Automatic sending needs a WhatsApp provider.** Set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_FROM` (see `.env.example`).
  - *Testing:* use Twilio's WhatsApp sandbox number; the owner first sends Twilio's "join <code>" message to it from his WhatsApp.
  - *Production:* WhatsApp lets a business message someone only within 24 hours of their last message to it, unless the message is an approved **template**. For a message every evening, create a template with one variable (`{{1}}` = the summary) in Twilio/Meta, get it approved, and put its id in `TWILIO_WHATSAPP_CONTENT_SID`. You also need a WhatsApp-enabled sender number (Meta business verification). Swapping to another provider (e.g. Meta Cloud API) means replacing the one function `notify.send_whatsapp`.
- **Without a provider nothing is sent by itself.** The message is still built and saved; Settings lists it as "not sent automatically" with an **Open in WhatsApp** button that opens a chat to the owner's own number with the text filled in; he taps send. 
- *Send today's message now* in Settings sends a test immediately and does not use up the 9 PM message.
- The scheduler runs inside the app process, so the app must be running at 9 PM. Set `NOTIFY_ENABLED=0` to disable it.

## Languages: English and Hindi (Devanagari)
- A header button switches the whole app between **English** and **हिन्दी**. The choice is remembered. All screen text, spoken replies, confirmations, errors, insights and WhatsApp reminder drafts come out in that one language (no Hinglish).
- The language is sent as an `X-Lang: en|hi` header; the server's messages are in `backend/i18n.py`, the screen text is in the `S` object in `frontend/index.html`. Adding a language = adding one more column to both.
- Voice input uses `hi-IN` or `en-IN` to match. Commands work in either language, e.g. “Add ₹50 credit for Ramesh”, “How much does Ramesh owe”, “Sold two cutting chai”, “रमेश के 50 रुपये उधार लिखो”, “रमेश का कितना बाकी है”, “आज का कुल 2700”.
- **One customer, either script:** “Ramesh” and “रमेश” are the same customer (`names.py` compares a sound-based key, e.g. Imran/इमरान, Lakshmi/लक्ष्मी). The name is shown as first entered. Different people with very similar sounds could in theory collide: use *Edit* to rename. On first start an existing database is migrated and any English/Hindi duplicates are merged with their ledgers.

## Daily product-wise sales
`GET /api/sales/daily?days=7|14|30` returns, for each day, cups and sales amount per product plus totals and the best seller. Shown in the **Sales** tab. Manual day totals are not split by product and appear in their own column.

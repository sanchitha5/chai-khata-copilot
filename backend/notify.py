"""Daily 9 PM sales summary, sent to the shopkeeper's own WhatsApp.

- A background thread (started by main.py) wakes every 30 s; from NOTIFY_HOUR (default 21) onwards it sends each
  shop that day's summary once. `outbox(shop_id, day)` is unique, so restarts or several workers never double-send,
  and a server that was down at 9 PM still sends later that evening.
- Delivery uses Twilio's WhatsApp API (TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_FROM). WhatsApp only lets a
  business message a person freely within 24 h of the person's last message to it; for the 9 PM message every day, set
  TWILIO_WHATSAPP_CONTENT_SID to an approved template with one variable ({{1}} = the summary text).
- With no provider the message is still built and saved in the outbox (status "not_configured"); Settings then offers an
  "Open in WhatsApp" link so the owner can send it to himself with one tap. Nothing is sent automatically in that case.
- Demo shops are never messaged.
"""
import os, re, time, logging
from datetime import datetime
import db, tools
log = logging.getLogger("chaikhata.notify")
HOUR = int(os.environ.get("NOTIFY_HOUR", "21"))
RETRY_AFTER, MAX_TRIES = 600, 3

def configured(): return all(os.environ.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM"))
def e164(phone):
    d = re.sub(r"\D", "", phone or "")
    return "+91" + d if len(d) == 10 else "+" + d
def _wa(n): n = n.strip(); return n if n.startswith("whatsapp:") else "whatsapp:" + (n if n.startswith("+") else "+" + n)
def send_whatsapp(phone, body):
    """-> (status, detail). status: sent | failed | not_configured"""
    if not configured(): return "not_configured", "WhatsApp provider not configured"
    try:
        import httpx, json
        sid = os.environ["TWILIO_ACCOUNT_SID"]
        data = {"To": _wa(e164(phone)), "From": _wa(os.environ["TWILIO_WHATSAPP_FROM"])}
        tpl = os.environ.get("TWILIO_WHATSAPP_CONTENT_SID")
        if tpl: data.update(ContentSid=tpl, ContentVariables=json.dumps({"1": " ".join(body.split())}))   # templates cannot contain newlines
        else: data["Body"] = body
        r = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", timeout=15, auth=(sid, os.environ["TWILIO_AUTH_TOKEN"]), data=data)
        return ("sent", "") if r.status_code < 300 else ("failed", f"HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        return "failed", str(e)[:200]
SENDER = send_whatsapp   # tests replace this

def deliver(c, shop, day, phone, lang, test=False):
    """Claim (shop, day) in the outbox, then send once. Returns the outbox row (dict) or None if it was not ours to send."""
    ts = tools.now()
    cur = c.execute("insert or ignore into outbox(shop_id,day,phone,body,status,attempts,created,updated) values(?,?,?,?,?,?,?,?)", (shop, day, phone, "", "sending", 0, ts, ts))
    if cur.rowcount == 0:   # already handled today: only a failed one may be retried, a few times, spaced out
        cur = c.execute("update outbox set status='sending', updated=? where shop_id=? and day=? and status='failed' and attempts<? and updated<=?", (ts, shop, day, MAX_TRIES, ts - RETRY_AFTER))
        if cur.rowcount == 0: c.commit(); return None
    c.commit()
    body = tools.daily_message(c, shop, lang)
    status, detail = SENDER(phone, body)
    c.execute("update outbox set body=?, status=?, detail=?, attempts=attempts+1, updated=? where shop_id=? and day=?", (body, status, detail, tools.now(), shop, day)); c.commit()
    return dict(day=day, status=status, body=body, detail=detail)

def tick(now=None):
    """Send today's summary to every shop that is due. Returns how many were attempted."""
    now = now or datetime.now()
    if now.hour < HOUR: return 0
    day, n = now.strftime("%Y-%m-%d"), 0
    c = db.conn()
    try:
        for s in c.execute("select s.id, s.lang, min(u.phone) phone from shops s join users u on u.shop_id=s.id where s.notify=1 and s.is_demo=0 group by s.id").fetchall():
            if deliver(c, s["id"], day, s["phone"], s["lang"] or "en"): n += 1
    finally: c.close()
    return n

def loop(stop):
    while not stop.wait(30):
        try: tick()
        except Exception: log.exception("daily message run failed")

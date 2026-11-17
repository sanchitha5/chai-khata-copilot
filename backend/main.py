import os, json, time, hashlib, secrets, uuid, re, sqlite3, threading
from contextlib import asynccontextmanager
from collections import defaultdict
from urllib.parse import quote
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import db, tools, nlu, notify
from i18n import T, lang_of
os.environ.setdefault("TZ", "Asia/Kolkata")     # "today" and the 9 PM message follow shop-local time (override with TZ=...)
try: time.tzset()
except AttributeError: pass                      # Windows: uses the system timezone
db.init()
@asynccontextmanager
async def lifespan(_):
    stop = threading.Event()
    if os.environ.get("NOTIFY_ENABLED", "1") != "0": threading.Thread(target=notify.loop, args=(stop,), daemon=True).start()
    yield
    stop.set()
app = FastAPI(title="Chai Khata Copilot", lifespan=lifespan)
RATE = int(os.environ.get("RATE_LIMIT_PER_MIN", "120")); HITS = defaultdict(list)
FRONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend", "index.html")

def get_db():
    c = db.conn()
    try: yield c
    finally: c.close()
def hpw(p, salt): return hashlib.pbkdf2_hmac("sha256", p.encode(), bytes.fromhex(salt), 120000).hex()
def new_session(c, uid, shop):
    tok = secrets.token_hex(24)
    with c: c.execute("insert into sessions(token,user_id,shop_id,created) values(?,?,?,?)", (tok, uid, shop, tools.now()))
    return {"token": tok}
def auth(authorization: str = Header(None), x_lang: str = Header("en"), c=Depends(get_db)):
    lg = lang_of(x_lang)
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, T(lg, "login_first"))
    tok = authorization[7:]
    s = c.execute("select * from sessions where token=?", (tok,)).fetchone()
    if not s: raise HTTPException(401, T(lg, "session_end"))
    t = time.time(); h = [x for x in HITS[tok] if t - x < 60]
    if len(h) >= RATE: raise HTTPException(429, T(lg, "rate"))
    h.append(t); HITS[tok] = h
    return dict(token=tok, user=s["user_id"], shop=s["shop_id"], last=s["last_customer"], lang=lg)

class Reg(BaseModel): shop: str; phone: str; password: str
class Login(BaseModel): phone: str; password: str
class Voice(BaseModel): text: str
class Confirm(BaseModel): pending_id: str
class Bill(BaseModel): text: str; supplier: str = ""

@app.get("/")
def home(): return FileResponse(FRONT)
@app.post("/api/register")
def register(b: Reg, x_lang: str = Header("en"), c=Depends(get_db)):
    lg = lang_of(x_lang)
    ph = re.sub(r"\D", "", b.phone)
    if len(ph) < 8 or len(b.password) < 6 or not b.shop.strip(): raise HTTPException(400, T(lg, "reg_bad"))
    if c.execute("select 1 from users where phone=?", (ph,)).fetchone(): raise HTTPException(409, T(lg, "reg_dup"))
    salt = secrets.token_hex(16)
    with c:
        sid = c.execute("insert into shops(name,lang) values(?,?)", (b.shop.strip()[:60], lg)).lastrowid
        uid = c.execute("insert into users(shop_id,phone,salt,pw) values(?,?,?,?)", (sid, ph, salt, hpw(b.password, salt))).lastrowid
        db.seed_products(c, sid)
    return new_session(c, uid, sid)
@app.post("/api/login")
def login(b: Login, x_lang: str = Header("en"), c=Depends(get_db)):
    u = c.execute("select * from users where phone=?", (re.sub(r"\D", "", b.phone),)).fetchone()
    if not u or not secrets.compare_digest(u["pw"], hpw(b.password, u["salt"])): raise HTTPException(401, T(lang_of(x_lang), "login_bad"))
    return new_session(c, u["id"], u["shop_id"])
@app.post("/api/demo")
def demo(c=Depends(get_db)):
    """Separate demo shop (is_demo=1). Re-calling resets it. Never touches real shops."""
    u = c.execute("select u.* from users u join shops s on s.id=u.shop_id where u.phone='demo' and s.is_demo=1").fetchone()
    if u: sid, uid = u["shop_id"], u["id"]
    else:
        salt = secrets.token_hex(16)
        with c:
            sid = c.execute("insert into shops(name,is_demo) values('Demo Chai Stall',1)").lastrowid
            uid = c.execute("insert into users(shop_id,phone,salt,pw) values(?,?,?,?)", (sid, "demo", salt, hpw(secrets.token_hex(8), salt))).lastrowid
    db.seed_products(c, sid); tools.seed_demo(c, sid)
    return new_session(c, uid, sid)

@app.post("/api/voice")
def voice(b: Voice, a=Depends(auth), c=Depends(get_db)):
    text = b.text.strip()[:300]
    if not text: raise HTTPException(400, T(a["lang"], "empty"))
    acts = nlu.parse_any(text, tools.parse_products(c, a["shop"]))
    no = lambda m: {"reply": m, "needs_confirmation": False}
    if not acts: return no(T(a["lang"], "no_parse"))
    for x in acts:
        if x.get("err"): return no(T(a["lang"], "e_" + x["err"]) + " " + T(a["lang"], "retry"))
        if x.get("name") == "@last":
            r = c.execute("select name from customers where id=? and shop_id=?", (a["last"], a["shop"])).fetchone() if a["last"] else None
            if not r: return no(T(a["lang"], "who"))
            x["name"] = r["name"]
    if all(x["k"] == "bal" for x in acts):
        out = []
        for x in acts:
            cu = tools.customer(c, a["shop"], x["name"])
            out.append(T(a["lang"], "bal_line", n=x["name"], b=tools.rs(tools.balance(c, a["shop"], cu["id"]))) if cu else T(a["lang"], "no_cust_q", n=x["name"]))
            if cu: c.execute("update sessions set last_customer=? where token=?", (cu["id"], a["token"])); c.commit()
        return no(" ".join(out))
    pid = uuid.uuid4().hex
    with c: c.execute("insert into pending(id,shop_id,user_id,actions,created) values(?,?,?,?,?)", (pid, a["shop"], a["user"], json.dumps(acts), tools.now()))
    hi = tools.names_hi(c, a["shop"]) if a["lang"] == "hi" else None
    lines = [tools.describe(x, a["lang"], hi) for x in acts]
    new = [x["name"] for x in acts if x["k"] == "credit" and not tools.customer(c, a["shop"], x["name"])]
    big = any(x.get("amt", 0) >= 2000 for x in acts)
    return {"needs_confirmation": True, "pending_id": pid, "lines": lines, "new_customers": new, "warn_big": big, "auto_ok": all(x["k"] == "sale" and x["qty"] <= 10 for x in acts),
            "reply": ". ".join(lines) + ". " + (T(a["lang"], "big") + " " if big else "") + T(a["lang"], "sure")}
@app.post("/api/confirm")
def confirm(b: Confirm, a=Depends(auth), c=Depends(get_db)):
    p = c.execute("select * from pending where id=? and shop_id=?", (b.pending_id, a["shop"])).fetchone()
    if not p: raise HTTPException(404, T(a["lang"], "pend_nf"))
    if p["status"] != "open": return {"ok": True, "duplicate": True, "replies": []}
    replies, last, sids = [], None, []
    try:
        with c:
            for i, x in enumerate(json.loads(p["actions"])):
                if x["k"] == "bal": continue
                r = tools.execute(c, a["shop"], a["user"], x, f"{p['id']}:{i}", a["lang"])
                replies.append(r["reply"]); last = r.get("customer_id") or last
                if r.get("sale_id"): sids.append(r["sale_id"])
            c.execute("update pending set status='done' where id=?", (p["id"],))
            if last: c.execute("update sessions set last_customer=? where token=?", (last, a["token"]))
    except ValueError as e: raise HTTPException(400, str(e))
    except sqlite3.IntegrityError: raise HTTPException(409, T(a["lang"], "dup_entry"))
    return {"ok": True, "replies": replies, "reply": " ".join(replies), "sale_ids": sids}
@app.post("/api/cancel")
def cancel(b: Confirm, a=Depends(auth), c=Depends(get_db)):
    with c: c.execute("update pending set status='cancelled' where id=? and shop_id=? and status='open'", (b.pending_id, a["shop"]))
    return {"ok": True}
@app.get("/api/dashboard")
def dash(a=Depends(auth), c=Depends(get_db)): return tools.dashboard(c, a["shop"], a["lang"])
@app.get("/api/sales/daily")
def sales_daily(days: int = 14, a=Depends(auth), c=Depends(get_db)): return tools.daily_sales(c, a["shop"], max(1, min(days, 90)))
@app.get("/api/customers")
def custs(a=Depends(auth), c=Depends(get_db)): return tools.customers(c, a["shop"])
@app.get("/api/inventory")
def inv(a=Depends(auth), c=Depends(get_db)): return tools.inventory(c, a["shop"])
@app.get("/api/reminder/{cid}")
def reminder(cid: int, a=Depends(auth), c=Depends(get_db)):
    """Draft only. Nothing is sent: the vendor opens the WhatsApp link and presses send themselves."""
    cu = c.execute("select * from customers where id=? and shop_id=?", (cid, a["shop"])).fetchone()
    if not cu: raise HTTPException(404, T(a["lang"], "cust_nf"))
    bal = tools.balance(c, a["shop"], cid)
    shop = c.execute("select name from shops where id=?", (a["shop"],)).fetchone()["name"]
    msg = T(a["lang"], "remind", n=cu["name"], s=shop, b=tools.rs(bal))
    ph = re.sub(r"\D", "", cu["phone"] or ""); ph = "91" + ph if len(ph) == 10 else ph
    return {"message": msg, "whatsapp_link": f"https://wa.me/{ph}?text={quote(msg)}", "sent": False}
@app.post("/api/bill/parse")
def bill_parse(b: Bill, a=Depends(auth)):
    """Takes OCR text (OCR itself is NOT bundled). Returns lines for the vendor to review and correct."""
    items, unread, total = [], [], None
    for ln in b.text.splitlines():
        ln = ln.strip()
        m = re.match(r"(.+?)\s+(\d+(?:\.\d+)?)\s*(?:x|×|@)\s*(\d+(?:\.\d+)?)\s*$", ln, re.I)
        t = re.match(r"(?:total|कुल)\D*(\d+(?:\.\d+)?)", ln, re.I)
        if m: items.append(dict(item=m[1].strip(), qty=float(m[2]), price=float(m[3]), stock_item=next((nlu.ITEM[w] for w in m[1].lower().split() if w in nlu.ITEM), None)))
        elif t: total = float(t[1])
        elif ln: unread.append(ln)
    calc = sum(i["qty"] * i["price"] for i in items)
    return dict(items=items, total=total if total is not None else calc, total_mismatch=total is not None and abs(total - calc) > 1, unread_lines=unread)
@app.post("/api/bill/confirm")
def bill_confirm(b: Bill, a=Depends(auth), c=Depends(get_db)):
    p = bill_parse(b, a); h = hashlib.sha256(re.sub(r"\s+", " ", b.text.lower()).encode()).hexdigest()
    if not p["items"]: raise HTTPException(400, T(a["lang"], "bill_none"))
    try:
        with c:
            c.execute("insert into bills(shop_id,supplier,total,hash,created) values(?,?,?,?,?)", (a["shop"], b.supplier, round(p["total"] * 100), h, tools.now()))
            c.execute("insert into expenses(shop_id,category,amount,created) values(?,?,?,?)", (a["shop"], "Purchases", round(p["total"] * 100), tools.now()))
            for i in p["items"]:
                if i["stock_item"]: tools.move(c, a["shop"], i["stock_item"], i["qty"], "bill")
            tools.audit(c, a["shop"], a["user"], "bill", f"{b.supplier} {p['total']}")
    except sqlite3.IntegrityError: raise HTTPException(409, T(a["lang"], "bill_dup"))
    return {"ok": True, "total": p["total"]}

class Quick(BaseModel): item: str; key: str; qty: float = 1; mode: str = "cash"
def _run(c, a, act, key):
    try:
        with c: r = tools.execute(c, a["shop"], a["user"], act, key, a["lang"])
    except ValueError as e: raise HTTPException(400, str(e))
    except sqlite3.IntegrityError: return {"ok": True, "duplicate": True}
    return {"ok": True, "sale_id": r.get("sale_id"), "reply": r["reply"]}
@app.post("/api/quick")
def quick(b: Quick, a=Depends(auth), c=Depends(get_db)):
    """One-tap sale (no voice, no confirm). `key` is a client-generated id so a double tap or retry never double-counts."""
    p = c.execute("select * from products where shop_id=? and name=? and active=1", (a["shop"], b.item)).fetchone()
    if not p or b.mode not in ("cash", "upi") or not 0 < b.qty <= 50: raise HTTPException(400, T(a["lang"], "bad_quick"))
    return _run(c, a, dict(k="sale", name=p["name"], qty=b.qty, price=p["price"] / 100, cost=p["cost"] / 100, mode=b.mode), f"q:{b.key}")
@app.post("/api/undo-sale/{sid}")
def undo_sale(sid: int, a=Depends(auth), c=Depends(get_db)):
    try:
        with c: tools.undo_sale(c, a["shop"], a["user"], sid, a["lang"])
    except ValueError as e: raise HTTPException(400, str(e))
    return {"ok": True}

# ---------- Settings: shop info, daily message, products, customers ----------
def _verify(c, a, pw):
    u = c.execute("select * from users where id=?", (a["user"],)).fetchone()
    return bool(pw) and secrets.compare_digest(u["pw"], hpw(pw, u["salt"]))
class ShopInfo(BaseModel): shop: str; owner: str = ""; address: str = ""; phone: str = ""; notify: bool = True; lang: str = "en"; password: str = ""
class NewPw(BaseModel): old: str; new: str
class Prod(BaseModel): name: str; name_hi: str = ""; price: float; cost: float = 0; keywords: str = ""
class CustEdit(BaseModel): name: str; phone: str = ""
@app.get("/api/settings")
def get_settings(a=Depends(auth), c=Depends(get_db)):
    sh = c.execute("select * from shops where id=?", (a["shop"],)).fetchone(); u = c.execute("select phone from users where id=?", (a["user"],)).fetchone()
    box = [dict(day=r["day"], status=r["status"], body=r["body"], created=r["created"]) for r in c.execute("select * from outbox where shop_id=? order by created desc, id desc limit 7", (a["shop"],))]
    return dict(shop=sh["name"], owner=sh["owner"] or "", address=sh["address"] or "", phone=u["phone"], notify=bool(sh["notify"]), lang=sh["lang"] or "en", is_demo=bool(sh["is_demo"]),
                notify_hour=notify.HOUR, wa_configured=notify.configured(), outbox=box)
@app.put("/api/settings/shop")
def put_shop(b: ShopInfo, a=Depends(auth), c=Depends(get_db)):
    lg = a["lang"]; sh = c.execute("select is_demo from shops where id=?", (a["shop"],)).fetchone()
    old = c.execute("select phone from users where id=?", (a["user"],)).fetchone()["phone"]
    ph = old if sh["is_demo"] else re.sub(r"\D", "", b.phone)
    if not b.shop.strip() or len(ph) < 8 and not sh["is_demo"]: raise HTTPException(400, T(lg, "shop_bad"))
    if ph != old:
        if not b.password: raise HTTPException(400, T(lg, "pw_need"))
        if not _verify(c, a, b.password): raise HTTPException(401, T(lg, "pw_wrong"))
        if c.execute("select 1 from users where phone=? and id!=?", (ph, a["user"])).fetchone(): raise HTTPException(409, T(lg, "reg_dup"))
    with c:
        c.execute("update shops set name=?, owner=?, address=?, notify=?, lang=? where id=?", (b.shop.strip()[:60], b.owner.strip()[:60], b.address.strip()[:200], int(b.notify), lang_of(b.lang), a["shop"]))
        if ph != old: c.execute("update users set phone=? where id=?", (ph, a["user"]))
        tools.audit(c, a["shop"], a["user"], "edit_shop", b.shop.strip()[:60])
    return {"ok": True}
@app.post("/api/settings/password")
def put_password(b: NewPw, a=Depends(auth), c=Depends(get_db)):
    if not _verify(c, a, b.old): raise HTTPException(401, T(a["lang"], "pw_wrong"))
    if len(b.new) < 6: raise HTTPException(400, T(a["lang"], "pw_short"))
    salt = secrets.token_hex(16)
    with c: c.execute("update users set salt=?, pw=? where id=?", (salt, hpw(b.new, salt), a["user"]))
    return {"ok": True}
@app.post("/api/settings/test-message")
def test_message(a=Depends(auth), c=Depends(get_db)):
    """Send today's summary right now (does not use up the 9 PM message)."""
    sh = c.execute("select lang from shops where id=?", (a["shop"],)).fetchone(); ph = c.execute("select phone from users where id=?", (a["user"],)).fetchone()["phone"]
    return notify.deliver(c, a["shop"], f"test-{tools.now()}", ph, sh["lang"] or a["lang"], test=True)

def _prod_vals(b, lg):
    name = " ".join(b.name.split())
    if not 0 < len(name) <= 30 or not 0 < b.price <= 10000 or not 0 <= b.cost <= 10000: raise HTTPException(400, T(lg, "prod_bad"))
    return name, " ".join(b.name_hi.split())[:30], round(b.price * 100), round(b.cost * 100), ", ".join(k.strip() for k in b.keywords.split(",") if k.strip())[:100]
@app.get("/api/products")
def get_products(a=Depends(auth), c=Depends(get_db)): return [tools.product_json(r) for r in tools.product_rows(c, a["shop"])]
@app.post("/api/products")
def add_product(b: Prod, a=Depends(auth), c=Depends(get_db)):
    name, hi, price, cost, kw = _prod_vals(b, a["lang"])
    old = c.execute("select * from products where shop_id=? and name=?", (a["shop"], name)).fetchone()
    with c:
        if old and old["active"]: raise HTTPException(409, T(a["lang"], "prod_dup"))
        if old: c.execute("update products set name=?, name_hi=?, price=?, cost=?, keywords=?, active=1, sort=(select coalesce(max(sort),0)+1 from products where shop_id=?) where id=?", (name, hi, price, cost, kw, a["shop"], old["id"])); pid = old["id"]
        else: pid = c.execute("insert into products(shop_id,name,name_hi,price,cost,keywords,sort) values(?,?,?,?,?,?,(select coalesce(max(sort),0)+1 from products where shop_id=?))", (a["shop"], name, hi, price, cost, kw, a["shop"])).lastrowid
        tools.audit(c, a["shop"], a["user"], "add_product", name)
    return {"ok": True, "id": pid}
@app.put("/api/products/{pid}")
def edit_product(pid: int, b: Prod, a=Depends(auth), c=Depends(get_db)):
    name, hi, price, cost, kw = _prod_vals(b, a["lang"])
    cur = c.execute("select * from products where id=? and shop_id=? and active=1", (pid, a["shop"])).fetchone()
    if not cur: raise HTTPException(404, T(a["lang"], "prod_nf"))
    if c.execute("select 1 from products where shop_id=? and name=? and id!=?", (a["shop"], name, pid)).fetchone(): raise HTTPException(409, T(a["lang"], "prod_dup"))
    with c:
        c.execute("update products set name=?, name_hi=?, price=?, cost=?, keywords=? where id=?", (name, hi, price, cost, kw, pid))
        if name != cur["name"]: c.execute("update sales set item=? where shop_id=? and item=?", (name, a["shop"], cur["name"]))   # keep history under the new name
        tools.audit(c, a["shop"], a["user"], "edit_product", f"{cur['name']} -> {name}")
    return {"ok": True}
@app.delete("/api/products/{pid}")
def remove_product(pid: int, a=Depends(auth), c=Depends(get_db)):
    """Soft delete: past sales keep their product name; it just stops showing as a button and stops matching voice."""
    with c:
        n = c.execute("update products set active=0 where id=? and shop_id=? and active=1", (pid, a["shop"])).rowcount
        if not n: raise HTTPException(404, T(a["lang"], "prod_nf"))
        tools.audit(c, a["shop"], a["user"], "remove_product", str(pid))
    return {"ok": True}
@app.put("/api/customers/{cid}")
def edit_customer(cid: int, b: CustEdit, a=Depends(auth), c=Depends(get_db)):
    try:
        with c: tools.update_customer(c, a["shop"], cid, b.name, b.phone, a["lang"])
    except ValueError as e: raise HTTPException(409 if str(e) == T(a["lang"], "cust_dup") else 400, str(e))
    return {"ok": True}

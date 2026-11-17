import os, json, time, hashlib, secrets, uuid, re, sqlite3
from collections import defaultdict
from urllib.parse import quote
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import db, tools, nlu
db.init()
app = FastAPI(title="Chai Khata Copilot")
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
def auth(authorization: str = Header(None), c=Depends(get_db)):
    if not authorization or not authorization.startswith("Bearer "): raise HTTPException(401, "Pehle login karein")
    tok = authorization[7:]
    s = c.execute("select * from sessions where token=?", (tok,)).fetchone()
    if not s: raise HTTPException(401, "Session khatam, dobara login karein")
    t = time.time(); h = [x for x in HITS[tok] if t - x < 60]
    if len(h) >= RATE: raise HTTPException(429, "Bahut zyada requests, thoda ruko")
    h.append(t); HITS[tok] = h
    return dict(token=tok, user=s["user_id"], shop=s["shop_id"], last=s["last_customer"])

class Reg(BaseModel): shop: str; phone: str; password: str
class Login(BaseModel): phone: str; password: str
class Voice(BaseModel): text: str
class Confirm(BaseModel): pending_id: str
class Bill(BaseModel): text: str; supplier: str = ""

@app.get("/")
def home(): return FileResponse(FRONT)
@app.post("/api/register")
def register(b: Reg, c=Depends(get_db)):
    ph = re.sub(r"\D", "", b.phone)
    if len(ph) < 8 or len(b.password) < 6 or not b.shop.strip(): raise HTTPException(400, "Dukaan ka naam, phone aur 6+ akshar ka password chahiye")
    if c.execute("select 1 from users where phone=?", (ph,)).fetchone(): raise HTTPException(409, "Yeh number pehle se registered hai")
    salt = secrets.token_hex(16)
    with c:
        sid = c.execute("insert into shops(name) values(?)", (b.shop.strip()[:60],)).lastrowid
        uid = c.execute("insert into users(shop_id,phone,salt,pw) values(?,?,?,?)", (sid, ph, salt, hpw(b.password, salt))).lastrowid
    return new_session(c, uid, sid)
@app.post("/api/login")
def login(b: Login, c=Depends(get_db)):
    u = c.execute("select * from users where phone=?", (re.sub(r"\D", "", b.phone),)).fetchone()
    if not u or not secrets.compare_digest(u["pw"], hpw(b.password, u["salt"])): raise HTTPException(401, "Phone ya password galat hai")
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
    tools.seed_demo(c, sid)
    return new_session(c, uid, sid)

@app.post("/api/voice")
def voice(b: Voice, a=Depends(auth), c=Depends(get_db)):
    text = b.text.strip()[:300]
    if not text: raise HTTPException(400, "Kuch bolein ya likhein")
    acts = nlu.parse_any(text)
    no = lambda m: {"reply": m, "needs_confirmation": False}
    if not acts: return no("Samajh nahi aaya. Aise boliye: Ramesh ko 50 rupaye udhaar likho")
    for x in acts:
        if x.get("err"): return no(x["err"] + ", dobara boliye")
        if x.get("name") == "@last":
            r = c.execute("select name from customers where id=? and shop_id=?", (a["last"], a["shop"])).fetchone() if a["last"] else None
            if not r: return no("Kiska? Naam bataiye")
            x["name"] = r["name"]
    if all(x["k"] == "bal" for x in acts):
        out = []
        for x in acts:
            cu = tools.customer(c, a["shop"], x["name"])
            out.append(f"{cu['name']} ka {tools.rs(tools.balance(c, a['shop'], cu['id']))} baaki hai" if cu else f"{x['name']} naam ka koi customer nahi hai")
            if cu: c.execute("update sessions set last_customer=? where token=?", (cu["id"], a["token"])); c.commit()
        return no(". ".join(out))
    pid = uuid.uuid4().hex
    with c: c.execute("insert into pending(id,shop_id,user_id,actions,created) values(?,?,?,?,?)", (pid, a["shop"], a["user"], json.dumps(acts), tools.now()))
    lines = [tools.describe(x) for x in acts]
    new = [x["name"] for x in acts if x["k"] == "credit" and not tools.customer(c, a["shop"], x["name"])]
    big = any(x.get("amt", 0) >= 2000 for x in acts)
    return {"needs_confirmation": True, "pending_id": pid, "lines": lines, "new_customers": new, "warn_big": big,
            "reply": ". ".join(lines) + (". Badi rakam hai, dobara check karein" if big else "") + ". Sahi hai?"}
@app.post("/api/confirm")
def confirm(b: Confirm, a=Depends(auth), c=Depends(get_db)):
    p = c.execute("select * from pending where id=? and shop_id=?", (b.pending_id, a["shop"])).fetchone()
    if not p: raise HTTPException(404, "Pending entry nahi mili")
    if p["status"] != "open": return {"ok": True, "duplicate": True, "replies": []}
    replies, last = [], None
    try:
        with c:
            for i, x in enumerate(json.loads(p["actions"])):
                if x["k"] == "bal": continue
                r = tools.execute(c, a["shop"], a["user"], x, f"{p['id']}:{i}")
                replies.append(r["reply"]); last = r.get("customer_id") or last
            c.execute("update pending set status='done' where id=?", (p["id"],))
            if last: c.execute("update sessions set last_customer=? where token=?", (last, a["token"]))
    except ValueError as e: raise HTTPException(400, str(e))
    except sqlite3.IntegrityError: raise HTTPException(409, "Yeh entry pehle ho chuki hai")
    return {"ok": True, "replies": replies, "reply": " ".join(replies)}
@app.post("/api/cancel")
def cancel(b: Confirm, a=Depends(auth), c=Depends(get_db)):
    with c: c.execute("update pending set status='cancelled' where id=? and shop_id=? and status='open'", (b.pending_id, a["shop"]))
    return {"ok": True}
@app.get("/api/dashboard")
def dash(a=Depends(auth), c=Depends(get_db)): return tools.dashboard(c, a["shop"])
@app.get("/api/customers")
def custs(a=Depends(auth), c=Depends(get_db)): return tools.customers(c, a["shop"])
@app.get("/api/inventory")
def inv(a=Depends(auth), c=Depends(get_db)): return tools.inventory(c, a["shop"])
@app.get("/api/reminder/{cid}")
def reminder(cid: int, a=Depends(auth), c=Depends(get_db)):
    """Draft only. Nothing is sent: the vendor opens the WhatsApp link and presses send themselves."""
    cu = c.execute("select * from customers where id=? and shop_id=?", (cid, a["shop"])).fetchone()
    if not cu: raise HTTPException(404, "Customer nahi mila")
    bal = tools.balance(c, a["shop"], cid)
    shop = c.execute("select name from shops where id=?", (a["shop"],)).fetchone()["name"]
    msg = f"Namaste {cu['name']}! {shop} par aapka {tools.rs(bal)} baaki hai. Jab ho tab de dijiye, dhanyavaad."
    ph = re.sub(r"\D", "", cu["phone"] or ""); ph = "91" + ph if len(ph) == 10 else ph
    return {"message": msg, "whatsapp_link": f"https://wa.me/{ph}?text={quote(msg)}", "sent": False}
@app.post("/api/bill/parse")
def bill_parse(b: Bill, a=Depends(auth)):
    """Takes OCR text (OCR itself is NOT bundled). Returns lines for the vendor to review and correct."""
    items, unread, total = [], [], None
    for ln in b.text.splitlines():
        ln = ln.strip()
        m = re.match(r"(.+?)\s+(\d+(?:\.\d+)?)\s*(?:x|×|@)\s*(\d+(?:\.\d+)?)\s*$", ln, re.I)
        t = re.match(r"total\D*(\d+(?:\.\d+)?)", ln, re.I)
        if m: items.append(dict(item=m[1].strip(), qty=float(m[2]), price=float(m[3]), stock_item=next((nlu.ITEM[w] for w in m[1].lower().split() if w in nlu.ITEM), None)))
        elif t: total = float(t[1])
        elif ln: unread.append(ln)
    calc = sum(i["qty"] * i["price"] for i in items)
    return dict(items=items, total=total if total is not None else calc, total_mismatch=total is not None and abs(total - calc) > 1, unread_lines=unread)
@app.post("/api/bill/confirm")
def bill_confirm(b: Bill, a=Depends(auth), c=Depends(get_db)):
    p = bill_parse(b, a); h = hashlib.sha256(re.sub(r"\s+", " ", b.text.lower()).encode()).hexdigest()
    if not p["items"]: raise HTTPException(400, "Koi item padha nahi gaya")
    try:
        with c:
            c.execute("insert into bills(shop_id,supplier,total,hash,created) values(?,?,?,?,?)", (a["shop"], b.supplier, round(p["total"] * 100), h, tools.now()))
            c.execute("insert into expenses(shop_id,category,amount,created) values(?,?,?,?)", (a["shop"], "Purchases", round(p["total"] * 100), tools.now()))
            for i in p["items"]:
                if i["stock_item"]: tools.move(c, a["shop"], i["stock_item"], i["qty"], "bill")
            tools.audit(c, a["shop"], a["user"], "bill", f"{b.supplier} {p['total']}")
    except sqlite3.IntegrityError: raise HTTPException(409, "Yeh bill pehle se daala ja chuka hai (duplicate)")
    return {"ok": True, "total": p["total"]}

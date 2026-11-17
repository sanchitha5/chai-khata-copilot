import os, tempfile
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db")
from fastapi.testclient import TestClient
import nlu, main
cl = TestClient(main.app)
def reg(n): return {"Authorization": "Bearer " + cl.post("/api/register", json={"shop": n, "phone": "9" + str(abs(hash(n)))[:9], "password": "secret1"}).json()["token"]}
def say(h, t, ok=True):
    r = cl.post("/api/voice", json={"text": t}, headers=h).json()
    if r.get("needs_confirmation"):
        r2 = cl.post("/api/confirm", json={"pending_id": r["pending_id"]}, headers=h)
        return r2.json() if ok else r2
    return r
def test_parser():
    a = nlu.parse("Ramesh ko 50 rupaye udhaar likho")[0]; assert (a["k"], a["name"], a["amt"]) == ("credit", "Ramesh", 50)
    s = nlu.parse("Do cutting chai aur ek masala chai"); assert [(x["name"], x["qty"]) for x in s] == [("Cutting chai", 2), ("Masala chai", 1)]
    d = nlu.parse("सुरेश को ३० रुपये उधार लिखो")[0]; assert (d["name"], d["amt"]) == ("सुरेश", 30)
    assert nlu.parse("usne 100 de diye")[0]["name"] == "@last"
    assert nlu.parse("20 packet doodh aaya")[0]["item"] == "Milk"
    p = lambda s: nlu.parse(s)[0]
    assert (p("Add 50 rupees credit for Ramesh")["k"], p("Add 50 rupees credit for Ramesh")["name"]) == ("credit", "Ramesh")
    assert (p("Ramesh paid 100 rupees")["k"], p("Ramesh paid 100 rupees")["amt"]) == ("payment", 100)
    assert (p("How much does Ramesh owe")["k"], p("How much does Ramesh owe")["name"]) == ("bal", "Ramesh")
    assert [(x["name"], x["qty"]) for x in nlu.parse("Sold two cutting chai and one masala chai")] == [("Cutting chai", 2), ("Masala chai", 1)]
    assert p("Spent 500 on milk")["cat"] == "Milk" and p("Bought 20 packets of milk")["item"] == "Milk"
    assert p("रमेश के 50 रुपये उधार लिखो")["name"] == "रमेश" and p("रमेश का कितना बाकी है")["k"] == "bal"
def test_ledger_context_and_idempotency():
    h = reg("A")
    say(h, "Ramesh ko 50 rupaye udhaar likho"); say(h, "Ramesh ko 150 rupaye udhaar likho")
    assert "200" in cl.post("/api/voice", json={"text": "Ramesh ka kitna baaki hai"}, headers=h).json()["reply"]
    assert "100" in say(h, "usne 100 de diye")["reply"]
    r = cl.post("/api/voice", json={"text": "Ramesh ko 10 rupaye udhaar likho"}, headers=h).json()
    cl.post("/api/confirm", json={"pending_id": r["pending_id"]}, headers=h)
    assert cl.post("/api/confirm", json={"pending_id": r["pending_id"]}, headers=h).json()["duplicate"]
    assert cl.get("/api/customers", headers=h).json()[0]["balance"] == 11000
    assert say(h, "Ramesh ne 5000 diye", ok=False).status_code == 400  # more than balance is rejected
def test_shop_isolation():
    a, b = reg("S1"), reg("S2")
    say(a, "Mohan ko 40 rupaye udhaar likho")
    assert "No customer named Mohan" in cl.post("/api/voice", json={"text": "Mohan ka kitna baaki"}, headers=b).json()["reply"]
    assert cl.get("/api/customers", headers=b).json() == []
    assert cl.get("/api/customers").status_code == 401
def test_demo_prediction_and_profit():
    h = {"Authorization": "Bearer " + cl.post("/api/demo").json()["token"]}
    d = cl.get("/api/dashboard", headers=h).json()
    assert d["prediction"]["cups"] > 0 and d["insights"] and len(cl.get("/api/customers", headers=h).json()) == 10
    assert d["est_profit"] == d["revenue"] - d["expenses"]
    before = d["revenue"]; say(h, "Do cutting chai"); assert cl.get("/api/dashboard", headers=h).json()["revenue"] == before + 2000
def test_bill_duplicate():
    h = reg("B"); t = "Doodh 20 x 30\nSugar 5 x 45\nTotal 825"
    assert cl.post("/api/bill/parse", json={"text": t}, headers=h).json()["total"] == 825
    assert cl.post("/api/bill/confirm", json={"text": t}, headers=h).status_code == 200
    assert cl.post("/api/bill/confirm", json={"text": t}, headers=h).status_code == 409

def test_quick_tap_and_undo_and_no_day_total():
    h = reg("Q")
    r = cl.post("/api/quick", json={"item": "Chai", "key": "k1"}, headers=h).json()
    assert cl.post("/api/quick", json={"item": "Chai", "key": "k1"}, headers=h).json().get("duplicate")  # double tap = one sale
    cl.post("/api/quick", json={"item": "Cutting chai", "key": "k2"}, headers=h)
    assert cl.get("/api/dashboard", headers=h).json()["revenue"] == 2200
    assert cl.post(f"/api/undo-sale/{r['sale_id']}", headers=h).status_code == 200
    assert cl.get("/api/dashboard", headers=h).json()["revenue"] == 1000
    assert cl.post("/api/day-total", json={"amt": 2700, "key": "d1"}, headers=h).status_code in (404, 405)   # feature removed
    assert nlu.parse("aaj ka total 500 hua") == []
    h2 = reg("Q2"); assert cl.post(f"/api/undo-sale/{r['sale_id']}", headers=h2).status_code == 400  # other shop cannot undo

def test_two_languages_no_hinglish():
    h = reg("L"); hh = {**h, "X-Lang": "hi"}
    en = say(h, "Add 50 rupees credit for Ramesh")["reply"]; assert en == "Added ₹50 credit for Ramesh. Total pending: ₹50."
    r = cl.post("/api/voice", json={"text": "रमेश के 70 रुपये उधार लिखो"}, headers=hh).json()
    assert "उधार" in r["lines"][0] and "Sahi" not in r["reply"]
    assert cl.post("/api/confirm", json={"pending_id": r["pending_id"]}, headers=hh).json()["reply"] == "रमेश के ₹70 उधार जोड़ दिए। कुल बाकी: ₹120।"
    assert cl.post("/api/voice", json={"text": "blah"}, headers=hh).json()["reply"].startswith("समझ नहीं आया")
    d = {"Authorization": "Bearer " + cl.post("/api/demo").json()["token"]}
    ih = " ".join(i["text"] for i in cl.get("/api/dashboard", headers={**d, "X-Lang": "hi"}).json()["insights"])
    ie = " ".join(i["text"] for i in cl.get("/api/dashboard", headers=d).json()["insights"])
    assert "पिछले" in ih and "Sales in the last" in ie
    for w in ("baaki", "udhaar", "kharcha", "bika", "kal ", "aur "): assert w not in (ih + ie + en).lower()

def test_auto_save_flag_for_small_sales_only():
    h = reg("AS")
    r = cl.post("/api/voice", json={"text": "Sold two cutting chai"}, headers=h).json(); assert r["auto_ok"]
    c = cl.post("/api/confirm", json={"pending_id": r["pending_id"]}, headers=h).json(); assert len(c["sale_ids"]) == 1
    assert not cl.post("/api/voice", json={"text": "Sold twenty chai"}, headers=h).json()["auto_ok"]      # large quantity needs a check
    assert not cl.post("/api/voice", json={"text": "Add 50 rupees credit for Ramesh"}, headers=h).json()["auto_ok"]  # money owed always confirmed

def test_daily_product_sales_table():
    h = reg("DS")
    for i, it in enumerate(["Chai", "Chai", "Cutting chai"]): cl.post("/api/quick", json={"item": it, "key": f"ds{i}"}, headers=h)
    d = cl.get("/api/sales/daily?days=7", headers=h).json()
    assert len(d["days"]) == 7 and d["products"] == ["Chai", "Cutting chai"]
    today = d["days"][0]["items"]; assert today["Chai"]["qty"] == 2 and today["Chai"]["rev"] == 2400 and today["Cutting chai"]["qty"] == 1
    assert d["best"] == "Chai" and d["qty"] == 3 and d["rev"] == 3400
    other = cl.get("/api/sales/daily", headers=reg("DS2")).json(); assert other["qty"] == 0 and other["best"] is None   # shop isolation
    demo = {"Authorization": "Bearer " + cl.post("/api/demo").json()["token"]}
    m = cl.get("/api/sales/daily?days=30", headers=demo).json()
    assert len(m["days"]) == 30 and abs(sum(v["rev"] for v in m["totals"].values()) - m["rev"]) <= 1 and m["best"]

def test_same_name_in_english_and_hindi_is_one_customer():
    import names
    for a, b in [("Ramesh", "रमेश"), ("Suresh", "सुरेश"), ("Imran", "इमरान"), ("Lakshmi", "लक्ष्मी"), ("Deepak", "दीपक")]: assert names.ckey(a) == names.ckey(b), (a, b)
    assert len({names.ckey(n) for n in ["Ramesh", "Suresh", "Anita", "Mohan", "Priya", "Imran", "Kavita", "Deepak", "Lakshmi", "Ganesh"]}) == 10
    h = reg("N"); say(h, "Ramesh ko 50 rupaye udhaar likho"); say(h, "रमेश के 70 रुपये उधार लिखो")
    cs = cl.get("/api/customers", headers=h).json(); assert len(cs) == 1 and cs[0]["balance"] == 12000 and cs[0]["name"] == "Ramesh"
    assert "120" in cl.post("/api/voice", json={"text": "रमेश का कितना बाकी है"}, headers=h).json()["reply"]
    assert "100" in say(h, "Ramesh ne 100 diye")["reply"]
    assert cl.get("/api/customers", headers=h).json()[0]["balance"] == 2000

def test_edit_customer():
    h = reg("EC"); say(h, "Ramesh ko 50 rupaye udhaar likho"); say(h, "Suresh ko 20 rupaye udhaar likho")
    ids = {c["name"]: c["id"] for c in cl.get("/api/customers", headers=h).json()}
    assert cl.put(f"/api/customers/{ids['Ramesh']}", json={"name": "रमेश कुमार", "phone": "98765 43210"}, headers=h).status_code == 200
    r = [c for c in cl.get("/api/customers", headers=h).json() if c["id"] == ids["Ramesh"]][0]; assert (r["name"], r["phone"], r["balance"]) == ("रमेश कुमार", "9876543210", 5000)
    assert cl.put(f"/api/customers/{ids['Ramesh']}", json={"name": "Suresh", "phone": ""}, headers=h).status_code == 409   # would duplicate another customer
    assert cl.put(f"/api/customers/{ids['Ramesh']}", json={"name": "", "phone": ""}, headers=h).status_code == 400
    assert cl.put(f"/api/customers/{ids['Ramesh']}", json={"name": "Ramesh", "phone": "12"}, headers=h).status_code == 400
    assert cl.put(f"/api/customers/{ids['Suresh']}", json={"name": "Suresh", "phone": ""}, headers=reg("EC2")).status_code == 400   # other shop's customer
    assert "9876543210" in cl.get(f"/api/reminder/{ids['Ramesh']}", headers=h).json()["whatsapp_link"]

def test_products_add_edit_remove_and_voice():
    h = reg("P"); hh = {**h, "X-Lang": "hi"}
    assert [p["name"] for p in cl.get("/api/products", headers=h).json()] == ["Chai", "Cutting chai", "Masala chai", "Coffee"]
    r = cl.post("/api/products", json={"name": "Samosa", "name_hi": "समोसा", "price": 15, "cost": 8, "keywords": "samose"}, headers=h); assert r.status_code == 200; pid = r.json()["id"]
    assert cl.post("/api/products", json={"name": "samosa", "price": 15}, headers=h).status_code == 409          # duplicate, case-insensitive
    assert cl.post("/api/products", json={"name": "Bad", "price": 0}, headers=h).status_code == 400
    assert "Samosa" in say(h, "teen samosa")["reply"] and cl.get("/api/dashboard", headers=h).json()["revenue"] == 4500
    assert say(h, "5 samose")["ok"] and cl.get("/api/dashboard", headers=h).json()["revenue"] == 12000
    assert cl.post("/api/quick", json={"item": "Samosa", "key": "s1"}, headers=h).status_code == 200
    v = cl.post("/api/voice", json={"text": "दो समोसा"}, headers=hh).json(); assert "समोसा" in v["lines"][0]
    assert cl.put(f"/api/products/{pid}", json={"name": "Samosa", "name_hi": "समोसा", "price": 20, "cost": 9, "keywords": "samose"}, headers=h).status_code == 200
    cl.post("/api/quick", json={"item": "Samosa", "key": "s2"}, headers=h); assert cl.get("/api/dashboard", headers=h).json()["revenue"] == 12000 + 1500 + 2000   # old sales keep the old price
    assert cl.put(f"/api/products/{pid}", json={"name": "Vada Pav", "price": 20}, headers=h).status_code == 200
    d = cl.get("/api/sales/daily?days=7", headers=h).json(); assert "Vada Pav" in d["products"] and "Samosa" not in d["products"]   # history follows the rename
    assert cl.put(f"/api/products/{pid}", json={"name": "Chai", "price": 20}, headers=h).status_code == 409
    assert cl.delete(f"/api/products/{pid}", headers=h).status_code == 200
    assert "Vada Pav" not in [p["name"] for p in cl.get("/api/products", headers=h).json()]
    assert cl.post("/api/quick", json={"item": "Vada Pav", "key": "s3"}, headers=h).status_code == 400            # removed: no more taps
    assert cl.get("/api/sales/daily?days=7", headers=h).json()["qty"] > 0                                          # but history stays
    assert cl.put(f"/api/products/{pid}", json={"name": "Vada Pav", "price": 20}, headers=h).status_code == 404
    assert cl.delete(f"/api/products/{cl.get('/api/products', headers=reg('P2')).json()[0]['id']}", headers=h).status_code == 404   # other shop's product
    assert cl.post("/api/products", json={"name": "Vada Pav", "price": 25}, headers=h).status_code == 200         # re-adding revives it
    chai_id = cl.get("/api/products", headers=h).json()[0]["id"]
    assert cl.put(f"/api/products/{chai_id}", json={"name": "Special Chai", "price": 13, "cost": 5, "keywords": "chai"}, headers=h).status_code == 200
    assert "Special Chai" in say(h, "ek chai")["reply"]

def test_settings_shop_info_and_password():
    h = reg("SS"); s = cl.get("/api/settings", headers=h).json(); assert s["shop"] == "SS" and s["notify"] and s["notify_hour"] == 21
    ph = s["phone"]
    assert cl.put("/api/settings/shop", json={"shop": "New Chai Point", "owner": "Raju", "address": "MG Road", "phone": ph, "notify": False, "lang": "hi"}, headers=h).status_code == 200
    s = cl.get("/api/settings", headers=h).json(); assert (s["shop"], s["owner"], s["address"], s["notify"], s["lang"]) == ("New Chai Point", "Raju", "MG Road", False, "hi")
    assert cl.put("/api/settings/shop", json={"shop": "X", "phone": "9123456780"}, headers=h).status_code == 400            # phone change needs password
    assert cl.put("/api/settings/shop", json={"shop": "X", "phone": "9123456780", "password": "wrong!!"}, headers=h).status_code == 401
    assert cl.put("/api/settings/shop", json={"shop": "X", "phone": "9123456780", "password": "secret1"}, headers=h).status_code == 200
    assert cl.get("/api/settings", headers=h).json()["phone"] == "9123456780"
    assert cl.post("/api/login", json={"phone": "9123456780", "password": "secret1"}).status_code == 200
    other = cl.post("/api/register", json={"shop": "O", "phone": "9000000001", "password": "secret1"}).json()["token"]
    assert cl.put("/api/settings/shop", json={"shop": "X", "phone": "9000000001", "password": "secret1"}, headers=h).status_code == 409
    assert cl.put("/api/settings/shop", json={"shop": " ", "phone": "9123456780"}, headers=h).status_code == 400
    assert cl.post("/api/settings/password", json={"old": "nope", "new": "abcdef"}, headers=h).status_code == 401
    assert cl.post("/api/settings/password", json={"old": "secret1", "new": "abc"}, headers=h).status_code == 400
    assert cl.post("/api/settings/password", json={"old": "secret1", "new": "abcdef"}, headers=h).status_code == 200
    assert cl.post("/api/login", json={"phone": "9123456780", "password": "abcdef"}).status_code == 200 and cl.post("/api/login", json={"phone": "9123456780", "password": "secret1"}).status_code == 401

def test_daily_message_text():
    import tools, db
    h = reg("DM"); cl.post("/api/quick", json={"item": "Chai", "key": "a"}, headers=h); cl.post("/api/quick", json={"item": "Chai", "key": "b", "mode": "upi"}, headers=h)
    say(h, "Spent 100 on milk"); say(h, "Ramesh ko 50 rupaye udhaar likho")
    c = db.conn(); shop = c.execute("select id from shops where name='DM'").fetchone()["id"]
    m = tools.daily_message(c, shop, "en"); c.close()
    for part in ("DM", "Sales ₹24 (2 cups; cash ₹12, UPI ₹12)", "Expenses ₹100", "estimated profit ₹-76", "Best seller: Chai", "Credit pending: ₹50"): assert part in m, (part, m)
    c = db.conn(); mh = tools.daily_message(c, shop, "hi"); c.close(); assert "बिक्री ₹24" in mh and "चाय" in mh and "baaki" not in mh.lower()

def test_nine_pm_scheduler_sends_once_and_never_to_demo():
    import notify, db
    from datetime import datetime
    sent = []; mode = {"s": "sent"}
    notify.SENDER = lambda ph, body: (sent.append((ph, body)) or (mode["s"], "" if mode["s"] == "sent" else "boom"))
    try:
        h = reg("SCH"); ph = cl.get("/api/settings", headers=h).json()["phone"]; cl.post("/api/quick", json={"item": "Chai", "key": "x"}, headers=h)
        cl.post("/api/demo")                                                 # demo shop exists but must not be messaged
        assert notify.tick(datetime(2026, 11, 15, 20, 59)) == 0 and not sent  # before 9 PM: nothing
        assert notify.tick(datetime(2026, 11, 15, 21, 0)) >= 1
        mine = [x for x in sent if x[0] == ph]; assert len(mine) == 1 and "Sales ₹12" in mine[0][1] and "SCH" in mine[0][1]
        assert not [x for x in sent if x[0] == "demo"]
        n = len(sent); notify.tick(datetime(2026, 11, 15, 21, 30)); notify.tick(datetime(2026, 11, 15, 23, 59)); assert len(sent) == n   # once per day
        box = cl.get("/api/settings", headers=h).json()["outbox"]; assert box[0]["status"] == "sent" and box[0]["day"] == "2026-11-15"
        notify.tick(datetime(2026, 11, 16, 21, 0)); assert len([x for x in sent if x[0] == ph]) == 2   # next day sends again
        cl.put("/api/settings/shop", json={"shop": "SCH", "phone": ph, "notify": False}, headers=h)    # switched off
        notify.tick(datetime(2026, 11, 17, 21, 0)); assert len([x for x in sent if x[0] == ph]) == 2
        cl.put("/api/settings/shop", json={"shop": "SCH", "phone": ph, "notify": True}, headers=h)
        mode["s"] = "failed"; notify.tick(datetime(2026, 11, 18, 21, 0)); k = len(sent); notify.tick(datetime(2026, 11, 18, 21, 1)); assert len(sent) == k   # failed: not hammered immediately
        assert cl.get("/api/settings", headers=h).json()["outbox"][0]["status"] == "failed"
        c = db.conn(); c.execute("update outbox set updated=updated-700 where status='failed'"); c.commit(); c.close()
        mode["s"] = "sent"; notify.tick(datetime(2026, 11, 18, 21, 20)); assert cl.get("/api/settings", headers=h).json()["outbox"][0]["status"] == "sent"   # retried later
        t = cl.post("/api/settings/test-message", headers=h).json(); assert t["status"] == "sent" and "SCH" in t["body"]
    finally: notify.SENDER = notify.send_whatsapp
    assert notify.send_whatsapp("9876543210", "x")[0] == "not_configured" and notify._wa("+919876543210") == "whatsapp:+919876543210" and notify._wa("whatsapp:+14155238886") == "whatsapp:+14155238886"
    assert notify.e164("9876543210") == "+919876543210"

def test_migration_merges_existing_english_hindi_duplicates():
    import sqlite3, tempfile, db
    p = os.path.join(tempfile.mkdtemp(), "old.db"); o = sqlite3.connect(p)
    o.executescript("""create table shops(id integer primary key, name text not null, is_demo integer default 0);
    create table users(id integer primary key, shop_id integer, phone text unique not null, salt text not null, pw text not null);
    create table sessions(token text primary key, user_id integer, shop_id integer, last_customer integer, created integer);
    create table customers(id integer primary key, shop_id integer not null, name text not null, key text not null, phone text default '', unique(shop_id,key));
    create table ledger(id integer primary key, shop_id integer not null, customer_id integer not null, kind text not null, amount integer not null, idem text, created integer not null, unique(shop_id,idem));
    insert into shops(id,name) values(1,'Old');
    insert into customers(id,shop_id,name,key,phone) values(1,1,'Ramesh','ramesh',''),(2,1,'रमेश','रमेश','9876543210'),(3,1,'Anita','anita','');
    insert into ledger(shop_id,customer_id,kind,amount,created) values(1,1,'credit',5000,1),(1,2,'credit',7000,2),(1,2,'payment',1000,3),(1,3,'credit',900,4);""")
    o.commit(); o.close(); old = db.DB; db.DB = p
    try:
        db.init(); db.init()   # second run is a no-op
        c = db.conn(); rows = c.execute("select name,phone from customers order by id").fetchall()
        assert [r["name"] for r in rows] == ["Ramesh", "Anita"] and rows[0]["phone"] == "9876543210"
        assert c.execute("select sum(case kind when 'credit' then amount else -amount end) b from ledger where customer_id=1").fetchone()["b"] == 11000
        assert c.execute("select count(*) n from products").fetchone()["n"] == 4 and c.execute("select notify from shops").fetchone()["notify"] == 1; c.close()
    finally: db.DB = old

def test_whatsapp_payload_goes_to_owner_own_number():
    import sys, types, notify
    seen = {}
    fake = types.SimpleNamespace(post=lambda url, **kw: (seen.update(url=url, **kw), types.SimpleNamespace(status_code=201, text=""))[1])
    old = sys.modules.get("httpx"); sys.modules["httpx"] = fake
    env = {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_WHATSAPP_FROM": "+14155238886"}
    os.environ.update(env)
    try:
        assert notify.send_whatsapp("98765 43210", "Line1\nLine2") == ("sent", "")
        assert seen["data"] == {"To": "whatsapp:+919876543210", "From": "whatsapp:+14155238886", "Body": "Line1\nLine2"} and seen["auth"] == ("AC1", "tok") and "AC1/Messages" in seen["url"]
        os.environ["TWILIO_WHATSAPP_CONTENT_SID"] = "HX9"            # production: approved template, one variable, no newlines
        notify.send_whatsapp("9876543210", "Line1\nLine2"); assert seen["data"]["ContentSid"] == "HX9" and "Body" not in seen["data"] and seen["data"]["ContentVariables"] == '{"1": "Line1 Line2"}'
        fake.post = lambda url, **kw: types.SimpleNamespace(status_code=400, text="bad"); assert notify.send_whatsapp("9876543210", "x")[0] == "failed"
    finally:
        for k in list(env) + ["TWILIO_WHATSAPP_CONTENT_SID"]: os.environ.pop(k, None)
        if old: sys.modules["httpx"] = old
        else: del sys.modules["httpx"]
    assert notify.send_whatsapp("9876543210", "x")[0] == "not_configured"

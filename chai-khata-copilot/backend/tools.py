"""Deterministic business tools. Money is integer paise; the parser/LLM never touches the DB directly."""
import time, math, random
from datetime import datetime, timedelta
import nlu
LIMIT = 10_000_000  # Rs 1,00,000 per action
USE = {"Milk": 0.1, "Sugar": 0.012, "Patti": 0.004, "Cups": 1.0}  # assumed usage per cup (estimate)
UNITS = {"Milk": "packet", "Sugar": "kg", "Patti": "kg", "Cups": "pcs"}
now = lambda: int(time.time())
def rs(p): return f"₹{p/100:g}"
def audit(c, shop, user, action, detail): c.execute("insert into audit(shop_id,user_id,action,detail,created) values(?,?,?,?,?)", (shop, user, action, detail, now()))
def customer(c, shop, name, create=False):
    key = name.lower()
    r = c.execute("select * from customers where shop_id=? and key=?", (shop, key)).fetchone()
    if r or not create: return r
    c.execute("insert into customers(shop_id,name,key) values(?,?,?)", (shop, name, key))
    return customer(c, shop, name)
def balance(c, shop, cid):
    return c.execute("select coalesce(sum(case kind when 'credit' then amount else -amount end),0) b from ledger where shop_id=? and customer_id=?", (shop, cid)).fetchone()["b"]
def move(c, shop, item, d, why):
    c.execute("insert into stock(shop_id,item,qty) values(?,?,?) on conflict(shop_id,item) do update set qty=qty+excluded.qty", (shop, item, d))
    c.execute("insert into stock_moves(shop_id,item,delta,reason,created) values(?,?,?,?,?)", (shop, item, d, why, now()))
def describe(a):
    k = a["k"]
    if k == "credit": return f"{a['name']}: ₹{a['amt']:g} udhaar"
    if k == "payment": return f"{a['name']}: ₹{a['amt']:g} mila"
    if k == "sale": return f"{a['qty']:g} {a['name']} bika (₹{a['qty']*a['price']:g}, {a['mode']})"
    if k == "exp": return f"{a['cat']} kharcha ₹{a['amt']:g}"
    if k == "stock": return f"{a['item']} +{a['qty']:g} stock"
    return f"{a['name']} ka baaki"
def execute(c, shop, user, a, idem):
    k = a["k"]
    if k in ("credit", "payment"):
        p = round(a["amt"] * 100)
        if not 0 < p <= LIMIT: raise ValueError("Rakam sahi nahi hai")
        cu = customer(c, shop, a["name"], create=(k == "credit"))
        if not cu: raise ValueError(f"{a['name']} naam ka koi customer nahi mila")
        bal = balance(c, shop, cu["id"])
        if k == "payment" and p > bal: raise ValueError(f"{cu['name']} ka sirf {rs(bal)} baaki hai, {rs(p)} nahi ho sakta")
        c.execute("insert into ledger(shop_id,customer_id,kind,amount,idem,created) values(?,?,?,?,?,?)", (shop, cu["id"], k, p, idem, now()))
        audit(c, shop, user, k, f"{cu['name']} {p}")
        return dict(reply=f"{cu['name']} ka {rs(p)} {'add' if k=='credit' else 'payment update'} kar diya. Ab {rs(balance(c, shop, cu['id']))} pending hai.", customer_id=cu["id"])
    if k == "sale":
        if not 0 < a["qty"] <= 500: raise ValueError("Quantity sahi nahi hai")
        c.execute("insert into sales(shop_id,item,qty,price,cost,mode,idem,created) values(?,?,?,?,?,?,?,?)", (shop, a["name"], a["qty"], a["price"]*100, a["cost"]*100, a["mode"], idem, now()))
        for i, r in USE.items(): move(c, shop, i, -a["qty"] * r, "sale")
        audit(c, shop, user, "sale", describe(a))
        return dict(reply=f"{a['qty']:g} {a['name']} likh diya.")
    if k == "exp":
        p = round(a["amt"] * 100)
        if not 0 < p <= LIMIT: raise ValueError("Rakam sahi nahi hai")
        c.execute("insert into expenses(shop_id,category,amount,idem,created) values(?,?,?,?,?)", (shop, a["cat"], p, idem, now()))
        audit(c, shop, user, "expense", describe(a))
        return dict(reply=f"{a['cat']} ka kharcha {rs(p)} likh diya.")
    if k == "stock":
        if a["item"] not in USE or a["qty"] <= 0: raise ValueError("Stock item sahi nahi hai")
        move(c, shop, a["item"], a["qty"], "purchase"); audit(c, shop, user, "stock", describe(a))
        return dict(reply=f"{a['item']} stock mein {a['qty']:g} jod diya.")
    raise ValueError("Unknown action")
def predict(c, shop):
    rows = c.execute("select date(created,'unixepoch','localtime') d, sum(qty) q from sales where shop_id=? and date(created,'unixepoch','localtime')<date('now','localtime') group by d", (shop,)).fetchall()
    if not rows: return None
    wd = (datetime.now().weekday() + 1) % 7
    same = [r["q"] for r in rows if datetime.strptime(r["d"], "%Y-%m-%d").weekday() == wd]
    src = same if len(same) >= 2 else [r["q"] for r in rows]
    cups = round(sum(src) / len(src))
    return dict(cups=cups, days=len(src), same_weekday=src is same, need={i: math.ceil(cups * r * 10) / 10 for i, r in USE.items()}, note="Estimate from past sales, not a guarantee")
def _sum(c, shop, a, b, cat=None):
    n = now(); t, col = ("expenses", "amount") if cat else ("sales", "qty*price")
    q = f"select coalesce(sum({col}),0) v from {t} where shop_id=? and created>=? and created<?" + (" and category=?" if cat else "")
    return c.execute(q, (shop, n - b * 86400, n - a * 86400) + ((cat,) if cat else ())).fetchone()["v"]
def insights(c, shop):
    o = []; n = now()
    w1, w0 = _sum(c, shop, 0, 7), _sum(c, shop, 7, 14)
    if w0 > 0: o.append(dict(type="fact", sev="info", text=f"Pichle 7 din ki bikri {rs(w1)}, usse pehle 7 din {rs(w0)} ({round((w1-w0)/w0*100):+d}%)."))
    m1, m0 = _sum(c, shop, 0, 7, "Milk"), _sum(c, shop, 7, 14, "Milk")
    if m0 > 0 and m1 > 0: o.append(dict(type="fact", sev="warn" if abs(m1/m0-1) > .1 else "info", text=f"Milk ka kharcha pichle hafte {abs(round((m1/m0-1)*100))}% {'badha' if m1>=m0 else 'ghata'} ({rs(m0)} se {rs(m1)})."))
    tp = c.execute("select item, sum(qty*(price-cost)) m from sales where shop_id=? and created>? group by item order by m desc limit 1", (shop, n - 30*86400)).fetchone()
    if tp: o.append(dict(type="estimate", sev="info", text=f"{tp['item']} se sabse zyada estimated munafa: {rs(tp['m'])} (pichle 30 din, recorded product cost par)."))
    pk = c.execute("select strftime('%H',created,'unixepoch','localtime') h, sum(qty) q from sales where shop_id=? and created>? group by h order by q desc limit 1", (shop, n - 30*86400)).fetchone()
    if pk: o.append(dict(type="fact", sev="info", text=f"Sabse zyada cups {int(pk['h'])}:00 se {int(pk['h'])+1}:00 ke beech bikte hain."))
    pr = predict(c, shop)
    if pr:
        st = {r["item"]: r["qty"] for r in c.execute("select item,qty from stock where shop_id=?", (shop,))}
        for i, need in pr["need"].items():
            have = max(0, st.get(i, 0))
            if have < need: o.append(dict(type="estimate", sev="critical", text=f"{i}: kal ~{need} {UNITS[i]} lag sakta hai, stock {have:.1f}. Lagbhag {math.ceil(need-have)} aur kharidein."))
    hi = c.execute("select name, b from (select cu.name, sum(case l.kind when 'credit' then l.amount else -l.amount end) b from ledger l join customers cu on cu.id=l.customer_id where l.shop_id=? group by cu.id) where b>0 order by b desc limit 1", (shop,)).fetchone()
    if hi: o.append(dict(type="fact", sev="warn" if hi["b"] >= 50000 else "info", text=f"Sabse zyada udhaar: {hi['name']} ka {rs(hi['b'])}."))
    return o
def dashboard(c, shop):
    t = "date(created,'unixepoch','localtime')=date('now','localtime')"
    s = c.execute(f"select coalesce(sum(qty*price),0) rev, coalesce(sum(qty),0) cups, coalesce(sum(case mode when 'upi' then qty*price else 0 end),0) upi, count(*) orders from sales where shop_id=? and {t}", (shop,)).fetchone()
    e = c.execute(f"select coalesce(sum(amount),0) v, count(*) n from expenses where shop_id=? and {t}", (shop,)).fetchone()
    pend = c.execute("select coalesce(sum(b),0) v from (select sum(case kind when 'credit' then amount else -amount end) b from ledger where shop_id=? group by customer_id) where b>0", (shop,)).fetchone()["v"]
    days = [dict(d=r["d"], rev=r["v"]) for r in c.execute("select date(created,'unixepoch','localtime') d, sum(qty*price) v from sales where shop_id=? group by d order by d desc limit 14", (shop,))][::-1]
    return dict(revenue=s["rev"], cups=s["cups"], upi=s["upi"], cash=s["rev"]-s["upi"], orders=s["orders"], expenses=e["v"], expenses_recorded=e["n"] > 0,
                est_profit=s["rev"]-e["v"], profit_note="Revenue minus recorded expenses" if e["n"] else "Incomplete: no expenses recorded today", pending_udhaar=pend,
                chart=days, insights=insights(c, shop), prediction=predict(c, shop))
def customers(c, shop):
    return [dict(r) for r in c.execute("select cu.id, cu.name, cu.phone, coalesce(sum(case l.kind when 'credit' then l.amount else -l.amount end),0) balance from customers cu left join ledger l on l.customer_id=cu.id where cu.shop_id=? group by cu.id order by balance desc", (shop,))]
def inventory(c, shop):
    pr = predict(c, shop); st = {r["item"]: r["qty"] for r in c.execute("select item,qty from stock where shop_id=?", (shop,))}
    return [dict(item=i, qty=round(max(0, st.get(i, 0)), 2), unit=UNITS[i], need_tomorrow=pr["need"][i] if pr else None) for i in USE]
def wipe(c, shop):
    for t in ("ledger", "customers", "sales", "expenses", "stock", "stock_moves", "pending", "audit", "bills"):
        c.execute(f"delete from {t} where shop_id=?", (shop,))
def seed_demo(c, shop):
    r = random.Random(42); n = now(); w = {7:.8,8:2,9:2,10:1.2,11:.5,15:.8,16:1.4,17:1.6,18:1.2,19:.6}
    with c:
        wipe(c, shop)
        for d in range(29, -1, -1):
            day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=d)
            base = (125 if day.weekday() == 6 else 105 if day.weekday() == 5 else 85) * (.9 + r.random() * .2); cups = 0
            for h, wt in w.items():
                t = int((day + timedelta(hours=h, minutes=r.random() * 30)).timestamp())
                if t > n: continue
                for _ in range(2):
                    p = r.choice(nlu.PROD); q = max(1, round(base * wt / 10 * (.6 + r.random() * .8) / 2)); cups += q
                    c.execute("insert into sales(shop_id,item,qty,price,cost,mode,created) values(?,?,?,?,?,?,?)", (shop, p[1], q, p[2]*100, p[3]*100, "cash" if r.random() < .65 else "upi", t))
            t = int((day + timedelta(hours=20)).timestamp())
            if t < n:
                ex = [("Milk", round(cups * .1 * 30 * (1.15 if d < 7 else 1))), ("Other", 60)] + ([("Patti", 300)] if d % 5 == 0 else []) + ([("Sugar", 180)] if d % 4 == 0 else []) + ([("Cups", 250)] if d % 7 == 0 else [])
                for cat, amt in ex: c.execute("insert into expenses(shop_id,category,amount,created) values(?,?,?,?)", (shop, cat, amt*100, t))
        for i, (nm, bal) in enumerate([("Ramesh",150),("Suresh",80),("Anita",220),("Mohan",40),("Priya",0),("Imran",310),("Kavita",120),("Deepak",520),("Lakshmi",60),("Ganesh",0)]):
            cur = c.execute("insert into customers(shop_id,name,key) values(?,?,?)", (shop, nm, nm.lower()))
            if bal: c.execute("insert into ledger(shop_id,customer_id,kind,amount,created) values(?,?,?,?,?)", (shop, cur.lastrowid, "credit", bal*100, n - (1+i*2)*86400))
        for it, q in {"Milk": 6, "Sugar": 6, "Patti": 1.5, "Cups": 60}.items(): c.execute("insert into stock(shop_id,item,qty) values(?,?,?)", (shop, it, q))

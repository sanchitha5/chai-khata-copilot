"""Deterministic business tools. Money is integer paise; the parser/LLM never touches the DB directly."""
import time, math, random, re
from datetime import datetime, timedelta
import nlu
from names import ckey
from i18n import T, L, U, MODE, RISE
LIMIT = 10_000_000  # Rs 1,00,000 per action
USE = {"Milk": 0.1, "Sugar": 0.012, "Patti": 0.004, "Cups": 1.0}  # assumed usage per cup (estimate)
UNITS = {"Milk": "packet", "Sugar": "kg", "Patti": "kg", "Cups": "pcs"}
now = lambda: int(time.time())
def rs(p): return f"₹{p/100:g}"
def audit(c, shop, user, action, detail): c.execute("insert into audit(shop_id,user_id,action,detail,created) values(?,?,?,?,?)", (shop, user, action, detail, now()))
def customer(c, shop, name, create=False):
    key = ckey(name)   # script-independent: "Ramesh" and "रमेश" are one customer
    r = c.execute("select * from customers where shop_id=? and key=?", (shop, key)).fetchone()
    if r or not create: return r
    c.execute("insert into customers(shop_id,name,key) values(?,?,?)", (shop, name.strip(), key))
    return customer(c, shop, name)
def balance(c, shop, cid):
    return c.execute("select coalesce(sum(case kind when 'credit' then amount else -amount end),0) b from ledger where shop_id=? and customer_id=?", (shop, cid)).fetchone()["b"]
def move(c, shop, item, d, why):
    c.execute("insert into stock(shop_id,item,qty) values(?,?,?) on conflict(shop_id,item) do update set qty=qty+excluded.qty", (shop, item, d))
    c.execute("insert into stock_moves(shop_id,item,delta,reason,created) values(?,?,?,?,?)", (shop, item, d, why, now()))
def names_hi(c, shop): return {r["name"]: r["name_hi"] for r in c.execute("select name,name_hi from products where shop_id=? and name_hi!=''", (shop,))}
def describe(a, lang="en", hi=None):
    k = a["k"]; m = lambda x: f"₹{x:g}"
    if k == "credit": return T(lang, "d_credit", n=a["name"], a=m(a["amt"]))
    if k == "payment": return T(lang, "d_pay", n=a["name"], a=m(a["amt"]))
    if k == "sale": return T(lang, "d_sale", q=f"{a['qty']:g}", i=L(lang, a["name"], hi), a=m(a["qty"] * a["price"]), m=MODE[lang][a["mode"]])
    if k == "exp": return T(lang, "d_exp", c=L(lang, a["cat"], hi), a=m(a["amt"]))
    if k == "stock": return T(lang, "d_stock", i=L(lang, a["item"]), q=f"{a['qty']:g}")
    return T(lang, "d_bal", n=a["name"])

def execute(c, shop, user, a, idem, lang="en"):
    k = a["k"]; E = lambda key, **kw: ValueError(T(lang, key, **kw))
    if k in ("credit", "payment"):
        p = round(a["amt"] * 100)
        if not 0 < p <= LIMIT: raise E("bad_amt")
        cu = customer(c, shop, a["name"], create=(k == "credit"))
        if not cu: raise E("no_cust", n=a["name"])
        bal = balance(c, shop, cu["id"])
        if k == "payment" and p > bal: raise E("over_pay", n=a["name"], b=rs(bal), p=rs(p))
        c.execute("insert into ledger(shop_id,customer_id,kind,amount,idem,created) values(?,?,?,?,?,?)", (shop, cu["id"], k, p, idem, now()))
        audit(c, shop, user, k, f"{cu['name']} {p}")
        return dict(reply=T(lang, "credit_ok" if k == "credit" else "pay_ok", n=a["name"], p=rs(p), b=rs(balance(c, shop, cu["id"]))), customer_id=cu["id"])
    if k == "sale":
        if not 0 < a["qty"] <= 500: raise E("bad_qty")
        cur = c.execute("insert into sales(shop_id,item,qty,price,cost,mode,idem,created) values(?,?,?,?,?,?,?,?)", (shop, a["name"], a["qty"], a["price"]*100, a["cost"]*100, a["mode"], idem, now()))
        for i, r in USE.items(): move(c, shop, i, -a["qty"] * r, "sale")
        audit(c, shop, user, "sale", describe(a))
        return dict(reply=T(lang, "sale_ok", q=f"{a['qty']:g}", i=L(lang, a["name"], names_hi(c, shop) if lang == "hi" else None)), sale_id=cur.lastrowid)
    if k == "exp":
        p = round(a["amt"] * 100)
        if not 0 < p <= LIMIT: raise E("bad_amt")
        c.execute("insert into expenses(shop_id,category,amount,idem,created) values(?,?,?,?,?)", (shop, a["cat"], p, idem, now()))
        audit(c, shop, user, "expense", describe(a))
        return dict(reply=T(lang, "exp_ok", c=L(lang, a["cat"]), p=rs(p)))
    if k == "stock":
        if a["item"] not in USE or a["qty"] <= 0: raise E("bad_item")
        move(c, shop, a["item"], a["qty"], "purchase"); audit(c, shop, user, "stock", describe(a))
        return dict(reply=T(lang, "stock_ok", q=f"{a['qty']:g}", i=L(lang, a["item"])))
    raise E("unknown")

def product_rows(c, shop):
    return c.execute("select * from products where shop_id=? and active=1 order by sort,id", (shop,)).fetchall()
def parse_products(c, shop):
    """(spoken words, name, price Rs, cost Rs) for each active product of this shop, used by the voice parser."""
    return [(nlu._kws(r["name"], r["keywords"] + "," + r["name_hi"]), r["name"], r["price"] / 100, r["cost"] / 100) for r in product_rows(c, shop)]
def product_json(r): return dict(id=r["id"], name=r["name"], name_hi=r["name_hi"], price=r["price"] / 100, cost=r["cost"] / 100, keywords=r["keywords"])
def update_customer(c, shop, cid, name, phone, lang="en"):
    name = " ".join(str(name).split()); ph = re.sub(r"\D", "", phone or "")
    if not 0 < len(name) <= 40 or (ph and not 8 <= len(ph) <= 15): raise ValueError(T(lang, "cust_bad"))
    cu = c.execute("select * from customers where id=? and shop_id=?", (cid, shop)).fetchone()
    if not cu: raise ValueError(T(lang, "cust_nf"))
    k = ckey(name)
    if c.execute("select 1 from customers where shop_id=? and key=? and id!=?", (shop, k, cid)).fetchone(): raise ValueError(T(lang, "cust_dup"))
    c.execute("update customers set name=?, key=?, phone=? where id=? and shop_id=?", (name, k, ph, cid, shop))
    audit(c, shop, None, "edit_customer", f"{cu['name']} -> {name}")
def daily_message(c, shop, lang="en", day=None):
    """Plain-text end-of-day summary (SMS-sized, no markup)."""
    day = day or datetime.now().strftime("%Y-%m-%d"); t = "date(created,'unixepoch','localtime')=?"
    s = c.execute(f"select coalesce(sum(qty*price),0) rev, coalesce(sum(qty),0) cups, coalesce(sum(case mode when 'upi' then qty*price else 0 end),0) upi from sales where shop_id=? and {t}", (shop, day)).fetchone()
    e = c.execute(f"select coalesce(sum(amount),0) v, count(*) n from expenses where shop_id=? and {t}", (shop, day)).fetchone()
    top = c.execute(f"select item from sales where shop_id=? and {t} group by item order by sum(qty) desc limit 1", (shop, day)).fetchone()
    pend = c.execute("select coalesce(sum(b),0) v from (select sum(case kind when 'credit' then amount else -amount end) b from ledger where shop_id=? group by customer_id) where b>0", (shop,)).fetchone()["v"]
    name = c.execute("select name from shops where id=?", (shop,)).fetchone()["name"]; hi = names_hi(c, shop)
    rev, upi = round(s["rev"]), round(s["upi"]); cups = f"{s['cups']:g}"
    out = [T(lang, "dm_head", s=name, d=datetime.strptime(day, "%Y-%m-%d").strftime("%d %b %Y"))]
    out.append(T(lang, "dm_sales", r=rs(rev), c=cups, ca=rs(rev - upi), u=rs(upi)) if s["cups"] else T(lang, "dm_none"))
    out.append(T(lang, "dm_exp", e=rs(e["v"]), p=rs(rev - e["v"])) if e["n"] else T(lang, "dm_noexp"))
    if top: out.append(T(lang, "dm_best", b=L(lang, top["item"], hi)))
    if pend: out.append(T(lang, "dm_pend", p=rs(pend)))
    return " ".join(out)

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
def insights(c, shop, lang="en"):
    o = []; n = now()
    w1, w0 = _sum(c, shop, 0, 7), _sum(c, shop, 7, 14)
    if w0 > 0: o.append(dict(type="fact", sev="info", text=T(lang, "i_wow", a=rs(w1), b=rs(w0), p=f"{round((w1-w0)/w0*100):+d}%")))
    m1, m0 = _sum(c, shop, 0, 7, "Milk"), _sum(c, shop, 7, 14, "Milk")
    if m0 > 0 and m1 > 0: o.append(dict(type="fact", sev="warn" if abs(m1/m0-1) > .1 else "info", text=T(lang, "i_milk", d=RISE[lang][0 if m1 >= m0 else 1], p=abs(round((m1/m0-1)*100)), a=rs(m0), b=rs(m1))))
    tp = c.execute("select item, sum(qty*(price-cost)) m from sales where shop_id=? and created>? and item!='Manual total' group by item order by m desc limit 1", (shop, n - 30*86400)).fetchone()
    if tp: o.append(dict(type="estimate", sev="info", text=T(lang, "i_top", i=L(lang, tp["item"]), a=rs(tp["m"]))))
    pk = c.execute("select strftime('%H',created,'unixepoch','localtime') h, sum(qty) q from sales where shop_id=? and created>? group by h order by q desc limit 1", (shop, n - 30*86400)).fetchone()
    if pk: o.append(dict(type="fact", sev="info", text=T(lang, "i_peak", h=int(pk["h"]), h2=int(pk["h"]) + 1)))
    pr = predict(c, shop)
    if pr:
        st = {r["item"]: r["qty"] for r in c.execute("select item,qty from stock where shop_id=?", (shop,))}
        for i, need in pr["need"].items():
            have = max(0, st.get(i, 0))
            if have < need: o.append(dict(type="estimate", sev="critical", text=T(lang, "i_short", i=L(lang, i), n=need, u=U(lang, UNITS[i]), s=f"{have:.1f}", x=math.ceil(need - have))))
    hi = c.execute("select name, b from (select cu.name, sum(case l.kind when 'credit' then l.amount else -l.amount end) b from ledger l join customers cu on cu.id=l.customer_id where l.shop_id=? group by cu.id) where b>0 order by b desc limit 1", (shop,)).fetchone()
    if hi: o.append(dict(type="fact", sev="warn" if hi["b"] >= 50000 else "info", text=T(lang, "i_cred", n=hi["name"], a=rs(hi["b"]))))
    return o

def dashboard(c, shop, lang="en"):
    t = "date(created,'unixepoch','localtime')=date('now','localtime')"
    s = c.execute(f"select coalesce(sum(qty*price),0) rev, coalesce(sum(qty),0) cups, coalesce(sum(case mode when 'upi' then qty*price else 0 end),0) upi, count(*) orders from sales where shop_id=? and {t}", (shop,)).fetchone()
    e = c.execute(f"select coalesce(sum(amount),0) v, count(*) n from expenses where shop_id=? and {t}", (shop,)).fetchone()
    pend = c.execute("select coalesce(sum(b),0) v from (select sum(case kind when 'credit' then amount else -amount end) b from ledger where shop_id=? group by customer_id) where b>0", (shop,)).fetchone()["v"]
    days = [dict(d=r["d"], rev=r["v"]) for r in c.execute("select date(created,'unixepoch','localtime') d, sum(qty*price) v from sales where shop_id=? group by d order by d desc limit 14", (shop,))][::-1]
    rev, upi = round(s["rev"]), round(s["upi"])
    return dict(revenue=rev, cups=s["cups"], upi=upi, cash=rev-upi, orders=s["orders"], expenses=e["v"], expenses_recorded=e["n"] > 0,
                est_profit=rev-e["v"], pending_udhaar=pend,
                chart=days, insights=insights(c, shop, lang), prediction=predict(c, shop))
def customers(c, shop):
    return [dict(r) for r in c.execute("select cu.id, cu.name, cu.phone, coalesce(sum(case l.kind when 'credit' then l.amount else -l.amount end),0) balance from customers cu left join ledger l on l.customer_id=cu.id where cu.shop_id=? group by cu.id order by balance desc", (shop,))]
def inventory(c, shop):
    pr = predict(c, shop); st = {r["item"]: r["qty"] for r in c.execute("select item,qty from stock where shop_id=?", (shop,))}
    return [dict(item=i, qty=round(max(0, st.get(i, 0)), 2), unit=UNITS[i], need_tomorrow=pr["need"][i] if pr else None) for i in USE]
def wipe(c, shop):
    for t in ("ledger", "customers", "sales", "expenses", "stock", "stock_moves", "pending", "audit", "bills", "outbox"):
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
                    p = r.choice(nlu.default_products()); q = max(1, round(base * wt / 10 * (.6 + r.random() * .8) / 2)); cups += q
                    c.execute("insert into sales(shop_id,item,qty,price,cost,mode,created) values(?,?,?,?,?,?,?)", (shop, p[1], q, int(p[2]*100), int(p[3]*100), "cash" if r.random() < .65 else "upi", t))
            t = int((day + timedelta(hours=20)).timestamp())
            if t < n:
                ex = [("Milk", round(cups * .1 * 30 * (1.15 if d < 7 else 1))), ("Other", 60)] + ([("Patti", 300)] if d % 5 == 0 else []) + ([("Sugar", 180)] if d % 4 == 0 else []) + ([("Cups", 250)] if d % 7 == 0 else [])
                for cat, amt in ex: c.execute("insert into expenses(shop_id,category,amount,created) values(?,?,?,?)", (shop, cat, amt*100, t))
        for i, (nm, bal) in enumerate([("Ramesh",150),("Suresh",80),("Anita",220),("Mohan",40),("Priya",0),("Imran",310),("Kavita",120),("Deepak",520),("Lakshmi",60),("Ganesh",0)]):
            cur = c.execute("insert into customers(shop_id,name,key) values(?,?,?)", (shop, nm, nm.lower()))
            if bal: c.execute("insert into ledger(shop_id,customer_id,kind,amount,created) values(?,?,?,?,?)", (shop, cur.lastrowid, "credit", bal*100, n - (1+i*2)*86400))
        for it, q in {"Milk": 6, "Sugar": 6, "Patti": 1.5, "Cups": 60}.items(): c.execute("insert into stock(shop_id,item,qty) values(?,?,?)", (shop, it, q))

def undo_sale(c, shop, user, sid, lang="en"):
    r = c.execute("select * from sales where id=? and shop_id=?", (sid, shop)).fetchone()
    if not r: raise ValueError(T(lang, "no_entry"))
    if r["created"] < now() - 86400: raise ValueError(T(lang, "undo_old"))
    for i, u in USE.items(): move(c, shop, i, r["qty"] * u, "undo")
    c.execute("delete from sales where id=? and shop_id=?", (sid, shop))
    audit(c, shop, user, "undo_sale", f"{r['item']} {r['qty']:g}")


def daily_sales(c, shop, days=14):
    """Per day, per product: quantity and revenue (paise). Days with no sales are included as zeros."""
    rows = c.execute("select date(created,'unixepoch','localtime') d, item, sum(qty) q, sum(qty*price) r from sales where shop_id=? and date(created,'unixepoch','localtime')>=date('now','localtime',?) group by d, item",
                     (shop, f"-{days - 1} days")).fetchall()
    names = {r["item"] for r in rows}
    order = [r["name"] for r in c.execute("select name from products where shop_id=? order by sort,id", (shop,))]   # current products first, in shop order; old/removed ones after
    products = [p for p in order if p in names] + sorted(names - set(order))
    out = {}
    for i in range(days):
        out[(datetime.now().date() - timedelta(days=i)).isoformat()] = {}
    for r in rows:
        if r["d"] in out: out[r["d"]][r["item"]] = dict(qty=r["q"], rev=round(r["r"]))
    tot = {p: dict(qty=0, rev=0) for p in products}
    ds = []
    for d, it in out.items():
        for p, v in it.items(): tot[p]["qty"] += v["qty"]; tot[p]["rev"] += v["rev"]
        ds.append(dict(date=d, items=it, qty=sum(v["qty"] for v in it.values()), rev=sum(v["rev"] for v in it.values())))
    best = max((p for p in products if p != "Manual total"), key=lambda p: tot[p]["qty"], default=None)
    return dict(products=products, days=ds, totals=tot, qty=sum(d["qty"] for d in ds), rev=sum(d["rev"] for d in ds), best=best if best and tot[best]["qty"] > 0 else None)

import sqlite3, os
from names import ckey
DB = os.environ.get("DB_PATH", "chaikhata.db")
SCHEMA = """
create table if not exists shops(id integer primary key, name text not null, is_demo integer default 0);
create table if not exists users(id integer primary key, shop_id integer not null references shops(id), phone text unique not null, salt text not null, pw text not null);
create table if not exists sessions(token text primary key, user_id integer not null references users(id), shop_id integer not null references shops(id), last_customer integer, created integer);
create table if not exists customers(id integer primary key, shop_id integer not null references shops(id), name text not null, key text not null, phone text default '', unique(shop_id,key));
create table if not exists ledger(id integer primary key, shop_id integer not null references shops(id), customer_id integer not null references customers(id), kind text not null check(kind in ('credit','payment')), amount integer not null check(amount>0), idem text, created integer not null, unique(shop_id,idem));
create table if not exists sales(id integer primary key, shop_id integer not null references shops(id), item text not null, qty real not null check(qty>0), price integer not null, cost integer not null, mode text not null check(mode in ('cash','upi')), idem text, created integer not null, unique(shop_id,idem));
create table if not exists expenses(id integer primary key, shop_id integer not null references shops(id), category text not null, amount integer not null check(amount>0), idem text, created integer not null, unique(shop_id,idem));
create table if not exists stock(shop_id integer not null references shops(id), item text not null, qty real not null default 0, primary key(shop_id,item));
create table if not exists stock_moves(id integer primary key, shop_id integer not null references shops(id), item text not null, delta real not null, reason text, created integer not null);
create table if not exists pending(id text primary key, shop_id integer not null references shops(id), user_id integer not null, actions text not null, status text not null default 'open', created integer not null);
create table if not exists audit(id integer primary key, shop_id integer not null references shops(id), user_id integer, action text not null, detail text, created integer not null);
create table if not exists bills(id integer primary key, shop_id integer not null references shops(id), supplier text, total integer, hash text not null, created integer not null, unique(shop_id,hash));
create table if not exists products(id integer primary key, shop_id integer not null references shops(id), name text not null collate nocase, name_hi text not null default '', price integer not null check(price>0), cost integer not null default 0 check(cost>=0), keywords text not null default '', sort integer not null default 0, active integer not null default 1, unique(shop_id,name));
create table if not exists outbox(id integer primary key, shop_id integer not null references shops(id), day text not null, phone text, body text, status text not null, detail text, attempts integer not null default 0, created integer not null, updated integer not null, unique(shop_id,day));
create index if not exists ix_sales on sales(shop_id,created);
create index if not exists ix_exp on expenses(shop_id,created);
create index if not exists ix_led on ledger(shop_id,customer_id);
"""
def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("pragma foreign_keys=on")
    return c
SHOP_COLS = {"owner": "text default ''", "address": "text default ''", "notify": "integer default 1", "lang": "text default 'en'"}
def seed_products(c, shop):
    """Give a shop the four default products if it has none yet (removed products stay as inactive rows, so this never re-adds them)."""
    import nlu
    if c.execute("select 1 from products where shop_id=?", (shop,)).fetchone(): return
    for i, p in enumerate(nlu.DEFAULTS):
        c.execute("insert into products(shop_id,name,name_hi,price,cost,keywords,sort) values(?,?,?,?,?,?,?)", (shop, p["name"], p["hi"], p["price"] * 100, p["cost"] * 100, p["kw"], i))
def _rekey(c):
    """One-time: make customer keys script-independent and merge customers that are now the same person."""
    rows = c.execute("select id,shop_id,name,phone from customers order by id").fetchall(); groups = {}
    for r in rows: groups.setdefault((r["shop_id"], ckey(r["name"])), []).append(r)
    c.execute("update customers set key='~'||id")
    for (shop, k), g in groups.items():
        keep = g[0]
        for o in g[1:]:
            c.execute("update ledger set customer_id=? where customer_id=?", (keep["id"], o["id"]))
            c.execute("update sessions set last_customer=? where last_customer=?", (keep["id"], o["id"]))
            if not keep["phone"] and o["phone"]: c.execute("update customers set phone=? where id=?", (o["phone"], keep["id"]))
            c.execute("delete from customers where id=?", (o["id"],))
        c.execute("update customers set key=? where id=?", (k, keep["id"]))
def init():
    c = conn(); c.executescript(SCHEMA)
    have = {r["name"] for r in c.execute("pragma table_info(shops)")}
    for k, v in SHOP_COLS.items():
        if k not in have: c.execute(f"alter table shops add column {k} {v}")
    if c.execute("pragma user_version").fetchone()[0] < 1:
        _rekey(c); c.execute("pragma user_version=1")
    for r in c.execute("select id from shops").fetchall(): seed_products(c, r["id"])
    c.commit(); c.close()

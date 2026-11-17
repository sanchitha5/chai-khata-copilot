import sqlite3, os
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
create index if not exists ix_sales on sales(shop_id,created);
create index if not exists ix_exp on expenses(shop_id,created);
create index if not exists ix_led on ledger(shop_id,customer_id);
"""
def conn():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("pragma foreign_keys=on")
    return c
def init():
    c = conn(); c.executescript(SCHEMA); c.commit(); c.close()

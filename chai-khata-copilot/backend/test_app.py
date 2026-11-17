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
    assert "koi customer nahi" in cl.post("/api/voice", json={"text": "Mohan ka kitna baaki"}, headers=b).json()["reply"]
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

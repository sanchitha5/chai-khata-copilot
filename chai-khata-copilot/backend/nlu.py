"""Hindi/Hinglish/English command parser. Rule-based by default; optional LLM (untested without a key)."""
import re, os, json
W = {"ek":1,"do":2,"teen":3,"char":4,"chaar":4,"paanch":5,"panch":5,"chhe":6,"saat":7,"aath":8,"nau":9,"das":10,"gyarah":11,"barah":12,"pandrah":15,"bees":20,"pachees":25,"tees":30,"chalis":40,"pachas":50,"saath":60,"sattar":70,"assi":80,"nabbe":90,"sau":100,"dedh":1.5,"dhai":2.5,
 "एक":1,"दो":2,"तीन":3,"चार":4,"पांच":5,"पाँच":5,"छह":6,"सात":7,"आठ":8,"नौ":9,"दस":10,"ग्यारह":11,"बारह":12,"पंद्रह":15,"बीस":20,"पच्चीस":25,"तीस":30,"चालीस":40,"पचास":50,"साठ":60,"सत्तर":70,"अस्सी":80,"नब्बे":90,"सौ":100}
PRON = {"usne","unhone","uska","usko","wo","woh","वो","उसने","उन्होंने","उसका"}
STOP = set(("ko ne ka ki ke को ने का की के likho likh karo kar do de dena rupaye rupees rupee rupiya rs paise रुपये रुपए रुपया लिखो लिख करो कर दे दो udhaar udhar credit उधार khata खाते खाता diye diya paid wapas jama mile दिए दिया वापस जमा मिले received payment kal aaj subah shaam liye for the a of to and please add write hai है kitna baaki baki hisab hisaab कितना बाकी हिसाब balance bataao batao aaya aayi stock kharcha kharch expense खर्च आया आई ek aur ji bhai bhaiya packet packets kg kilo litre liter").split()) | PRON
ITEM = {"doodh":"Milk","दूध":"Milk","milk":"Milk","chini":"Sugar","cheeni":"Sugar","चीनी":"Sugar","sugar":"Sugar","patti":"Patti","पत्ती":"Patti","cup":"Cups","cups":"Cups","कप":"Cups"}
PROD = [(r"cutting|कटिंग","Cutting chai",10,4),(r"masala|मसाला","Masala chai",15,6),(r"coffee|cofee|कॉफी|कॉफ़ी","Coffee",20,8),(r"chai|chay|चाय","Chai",12,5)]
MK = {"ko","ne","ka","ki","ke","को","ने","का","की","के"}
UDH = re.compile(r"udhaar|udhar|credit|उधार|khata|खाते")
NOSALE = re.compile(r"mangw|mangaw|order|patti|पत्ती|udhaar|udhar|उधार|credit|kitna|baaki|बाकी")
def num(t):
    return float(t) if re.fullmatch(r"\d+(\.\d+)?", t) else W.get(t)
def grab(t):
    acc = None
    for x in t:
        n = num(x)
        if n is None:
            if acc is not None: break
            continue
        acc = n if acc is None else (acc * 100 if n == 100 and acc < 10 else acc + n)
    return acc
def clean(s):
    s = s.lower().translate(str.maketrans("०१२३४५६७८९", "0123456789"))
    return re.sub(r"\s+", " ", re.sub(r"[₹!?\"“”]", " ", s)).strip()
def cap(n): return n[0].upper() + n[1:] if n and n[0].isascii() else n
def pc(s):
    t = s.split(); g = grab(t)
    if g and re.search(r"kharch|expense|खर्च", s): k = "exp"
    elif g and re.search(r"aaya|aayi|aa gaya|stock|आया|आई|खरीद", s) and not UDH.search(s): k = "stock"
    elif re.search(r"chai|chay|coffee|cofee|चाय|कॉफी|कॉफ़ी", s) and not NOSALE.search(s): k = "sale"
    elif UDH.search(s): k = "credit"
    elif re.search(r"\b(diye|diya|paid|wapas|jama|mile|received|payment)\b|दिए|दिया|वापस|जमा|मिले", s): k = "payment"
    elif re.search(r"kitna|baaki|baki|hisab|hisaab|बाकी|कितना|हिसाब|balance", s): k = "bal"
    elif g and re.search(r"likh|लिख|add|write", s): k = "credit"
    else: return None
    if k == "sale":
        p = next(x for x in PROD if re.search(x[0], s))
        return dict(k=k, name=p[1], qty=g or 1, price=p[2], cost=p[3], mode="upi" if re.search(r"upi|gpay|phonepe", s) else "cash")
    if k == "exp":
        return dict(k=k, cat=next((ITEM[x] for x in t if x in ITEM), "Other"), amt=g)
    if k == "stock":
        it = next((ITEM[x] for x in t if x in ITEM), None)
        return dict(k=k, item=it, qty=g) if it else dict(k=k, err="Kaunsa saaman aaya, samajh nahi aaya")
    name = "@last" if any(x in PRON for x in t) else None
    if not name:
        for i, x in enumerate(t):
            if x in MK and i > 0 and num(t[i-1]) is None and t[i-1] not in STOP: name = t[i-1]; break
            if x == "for" and i + 1 < len(t) and num(t[i+1]) is None and t[i+1] not in STOP: name = t[i+1]; break
        name = name or next((x for x in t if x not in STOP and num(x) is None), None)
    if not name: return dict(k=k, err="Naam samajh nahi aaya")
    if k == "bal": return dict(k=k, name=name if name == "@last" else cap(name))
    if not g or g <= 0: return dict(k=k, err="Rakam samajh nahi aayi")
    return dict(k=k, name=name if name == "@last" else cap(name), amt=g)
def parse(text):
    parts = re.split(r"[,;।]|\s+(?:aur|and|और|phir|then)\s+", text, flags=re.I)
    return [a for a in (pc(clean(p)) for p in parts if p.strip()) if a]
SYS = ('Convert the shopkeeper utterance into a JSON list only. Items: {"k":"credit|payment|bal","name":str,"amt":number} | '
       '{"k":"sale","name":str,"qty":number,"price":number,"cost":number,"mode":"cash|upi"} | {"k":"exp","cat":str,"amt":number} | {"k":"stock","item":"Milk|Sugar|Patti|Cups","qty":number}. Use name "@last" for pronouns.')
def _valid(a):
    need = {"credit":["name","amt"],"payment":["name","amt"],"bal":["name"],"sale":["name","qty","price","cost"],"exp":["cat","amt"],"stock":["item","qty"]}.get(a.get("k"))
    return bool(need) and all(f in a for f in need) and all(isinstance(a[f], (int, float)) and a[f] > 0 for f in ("amt","qty","price") if f in a)
def llm_parse(text):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key: return None
    try:
        import httpx
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=15,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
            json={"model": os.environ.get("LLM_MODEL", "claude-sonnet-5-5"), "max_tokens": 500, "system": SYS, "messages": [{"role": "user", "content": text}]})
        acts = json.loads(r.json()["content"][0]["text"])
        return acts if acts and all(_valid(a) for a in acts) else None
    except Exception:
        return None
def parse_any(text): return llm_parse(text) or parse(text)

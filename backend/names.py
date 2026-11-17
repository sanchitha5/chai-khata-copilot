"""Script-independent customer name key, so "Ramesh" and "रमेश" are the same customer.

Both scripts are reduced to a rough sound skeleton: Devanagari is transliterated, then
aspirates/long vowels are folded and the short vowel 'a' is dropped (Hindi speakers and
spellers differ on it: Imran / इमरान). Not perfect phonetics, but stable and deterministic.
"""
import re
_C = {"क":"k","ख":"k","ग":"g","घ":"g","ङ":"n","च":"C","छ":"C","ज":"j","झ":"j","ञ":"n","ट":"t","ठ":"t","ड":"d","ढ":"d","ण":"n","त":"t","थ":"t","द":"d","ध":"d","न":"n",
      "प":"p","फ":"p","ब":"b","भ":"b","म":"m","य":"y","र":"r","ल":"l","व":"v","श":"s","ष":"s","स":"s","ह":"h","ळ":"l"}
_IV = {"अ":"a","आ":"a","इ":"i","ई":"i","उ":"u","ऊ":"u","ए":"e","ऐ":"E","ओ":"o","औ":"O","ऋ":"ri"}
_M = {"ा":"a","ि":"i","ी":"i","ु":"u","ू":"u","े":"e","ै":"E","ो":"o","ौ":"O","ृ":"ri"}
def _dev(s):
    out, i = [], 0
    while i < len(s):
        ch = s[i]
        if ch in _C:
            out.append(_C[ch]); n = s[i + 1] if i + 1 < len(s) else ""
            if n == "़": i += 1; n = s[i + 1] if i + 1 < len(s) else ""
            if n == "्": i += 1                       # virama: no vowel
            elif n in _M: out.append(_M[n]); i += 1
            else: out.append("a")                      # inherent vowel
        elif ch in _IV: out.append(_IV[ch])
        elif ch in "ंँ": out.append("n")
        elif ch == "ः": out.append("h")
        elif ch in _M: out.append(_M[ch])
        elif ch in "़्": pass
        else: out.append(ch)
        i += 1
    return "".join(out)
def ckey(name):
    s = _dev(str(name or "").translate(str.maketrans("०१२३४५६७८९", "0123456789")).lower())
    s = re.sub(r"[^a-zA-Z0-9]", "", s)
    s = re.sub(r"chh?", "C", s)
    s = s.replace("sh", "s").replace("ai", "E").replace("au", "O")
    s = re.sub(r"([kgjtdpb])h", r"\1", s)                # aspirates
    s = s.replace("c", "k").replace("q", "k").replace("w", "v").replace("z", "j").replace("f", "p").replace("x", "ks")
    s = re.sub(r"ee|ii", "i", s); s = re.sub(r"oo|uu", "u", s)
    s = re.sub(r"(?<=[^aeiouEO])h", "", s)                 # h after a consonant is only an aspirate
    s = s.replace("a", "")
    s = re.sub(r"(.)\1+", r"\1", s)
    return s or str(name or "").strip().lower()

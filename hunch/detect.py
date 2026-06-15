# -*- coding: utf-8 -*-
"""Anomalie-/Chancen-Erkennung — vergleicht aktuelles fenster vs baseline.
Signale: topic-spike (neu/auffaellig), dormant-revival (altes projekt ausgegraben),
unusual-hours (zu ungewohnter zeit aktiv), opportunity (graph-dot-connect zum aktuellen fokus).
Robust gegen duenne live-daten: degradiert sauber, opportunities greifen sofort."""
import time, math, datetime, collections
from . import store, graph

def recent_focus(hours=8, k=8):
    """woran arbeitet er GRAD: entitaeten aus letzten events (fenstertitel) + messages."""
    since = time.time() - hours * 3600
    texts = []
    with store.cursor() as con:
        for r in con.execute("SELECT title FROM events WHERE ts>? AND title IS NOT NULL ORDER BY ts DESC LIMIT 200", (since,)):
            texts.append(r["title"])
        for r in con.execute("SELECT text FROM messages WHERE ts>? ORDER BY ts DESC LIMIT 80", (since,)):
            texts.append(r["text"])
    freq = collections.Counter()
    for t in texts:
        freq.update(graph.extract_entities(t))
    return [e for e, _ in freq.most_common(k)]

def detect_opportunities(focus, k=4):
    sig = []
    if not focus:
        return sig
    for c in graph.dot_connect(focus, k=k):
        if c["entity"] and c["strength"] >= 3:
            sig.append({
                "type": "opportunity",
                "score": round(min(0.95, 0.5 + math.log1p(c["strength"]) / 12), 2),
                "text": f"Dein aktueller Fokus haengt stark mit '{c['entity']}' zusammen — evtl. dort eine Idee/Loesung?",
                "data": {"focus": focus[:3], "bridge": c["entity"], "strength": c["strength"]},
            })
    return sig

def detect_topic_spikes(hours=8):
    """themen die GRAD haeufig sind aber in der baseline selten/neu."""
    base = {t["term"]: t["n"] for t in (store.get_profile("top_topics") or [])}
    base_max = max(base.values()) if base else 1
    since = time.time() - hours * 3600
    from .baseline import _tokens
    sig = []
    rec = collections.Counter()
    with store.cursor() as con:
        for r in con.execute("SELECT title FROM events WHERE ts>? AND title IS NOT NULL", (since,)):
            rec.update(_tokens(r["title"]))
        for r in con.execute("SELECT text FROM messages WHERE ts>?", (since,)):
            rec.update(_tokens(r["text"]))
    for term, n in rec.most_common(15):
        if n >= 4:
            base_share = base.get(term, 0) / base_max
            if base_share < 0.15:   # in baseline selten -> spike
                sig.append({
                    "type": "topic_spike", "score": round(min(0.9, 0.5 + n / 30), 2),
                    "text": f"Neues/auffaelliges Thema gerade: '{term}' ({n}x) — taucht in deiner Norm kaum auf.",
                    "data": {"term": term, "recent_n": n},
                })
    return sig[:3]

def detect_dormant_revival(dormant_days=21, recent_hours=12):
    """entitaet war lang inaktiv und taucht GRAD wieder auf."""
    now = time.time()
    rec_since = now - recent_hours * 3600
    dormant_before = now - dormant_days * 86400
    sig = []
    with store.cursor() as con:
        rows = con.execute(
            "SELECT name, first_seen, last_seen, count FROM entities "
            "WHERE last_seen>? AND first_seen<? AND count>=4 ORDER BY count DESC LIMIT 30",
            (rec_since, dormant_before)).fetchall()
    for r in rows:
        gap_days = (rec_since - r["first_seen"]) / 86400
        sig.append({
            "type": "dormant_revival", "score": 0.7,
            "text": f"Du greifst gerade '{r['name']}' wieder auf — war lange ruhig. Altes Projekt das zurueckkommt?",
            "data": {"entity": r["name"], "count": r["count"]},
        })
    return sig[:2]

def detect_unusual_hours():
    ah = store.get_profile("active_hours_real") or {}
    total = sum(ah.values()) or 0
    if total < 40:     # noch zu wenig live-daten fuer rhythmus-aussage
        return []
    h = str(datetime.datetime.now().hour)
    share = ah.get(h, 0) / total
    if share < 0.01:
        return [{"type": "unusual_hours", "score": 0.6,
                 "text": f"Du bist um {h} Uhr aktiv — sonst fast nie. Alles ok, oder grad im flow/wach?",
                 "data": {"hour": h, "share": round(share, 3)}}]
    return []

def run(focus_override=None):
    focus = focus_override or recent_focus()
    signals = []
    signals += detect_opportunities(focus)
    signals += detect_topic_spikes()
    signals += detect_dormant_revival()
    signals += detect_unusual_hours()
    signals.sort(key=lambda s: -s["score"])
    return {"focus": focus, "signals": signals}

if __name__ == "__main__":
    import json, sys
    fo = None
    if "--focus" in sys.argv:
        fo = sys.argv[sys.argv.index("--focus") + 1].split(",")
    print(json.dumps(run(focus_override=fo), indent=1, ensure_ascii=False))

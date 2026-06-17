# -*- coding: utf-8 -*-
"""Anomalie-/Chancen-Erkennung — vergleicht aktuelles fenster vs baseline.
Signale: topic-spike (neu/auffaellig), dormant-revival (altes projekt ausgegraben),
unusual-hours (zu ungewohnter zeit aktiv), opportunity (graph-dot-connect zum aktuellen fokus).
Robust gegen duenne live-daten: degradiert sauber, opportunities greifen sofort."""
import time, math, datetime, collections
from . import store, graph

# LIVE-quellen = echte aktuelle aktivitaet (konversation). Massen-INGEST (archive/vault/device/
# claude-mem) wird fuer die RECENT-erkennung AUSGESCHLOSSEN — sonst feuern signale auf alten
# importierten dateien (deren mtime "neu" aussieht) statt auf dem was du GERADE tust.
LIVE_SOURCES = ("session",)
_LIVE_IN = "(" + ",".join("?" * len(LIVE_SOURCES)) + ")"

def recent_focus(hours=8, k=8):
    """woran arbeitet er GRAD: entitaeten aus letzten events (fenstertitel) + LIVE-messages."""
    since = time.time() - hours * 3600
    texts = []
    with store.cursor() as con:
        for r in con.execute("SELECT title FROM events WHERE ts>? AND title IS NOT NULL ORDER BY ts DESC LIMIT 200", (since,)):
            texts.append(r["title"])
        for r in con.execute(
                f"SELECT text FROM messages WHERE ts>? AND source IN {_LIVE_IN} ORDER BY ts DESC LIMIT 80",
                (since, *LIVE_SOURCES)):
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
        for r in con.execute(
                f"SELECT text FROM messages WHERE ts>? AND source IN {_LIVE_IN}", (since, *LIVE_SOURCES)):
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

def hypothesis(sig, focus):
    """KAUSALE hypothese: verfolgt ein signal durch den graph zurueck -> WARUM + naechster schritt.
    nutzt die entity-typen (person kann helfen / tool passt / topic uebertragbar). der unterschied
    zwischen 'du denkst an X' (beobachtung) und 'X haengt an Y das dich blockiert, probier Z' (intuition)."""
    typ = sig.get("type")
    d = sig.get("data", {}) or {}
    try:
        if typ == "topic_spike":
            term = d.get("term")
            nbs = graph.neighbors(term, k=4)
            strong = nbs[0][0] if nbs else None
            if strong:
                k = graph.kind_of(strong)
                rolle = {"person": f"hat mit '{strong}' zu tun", "tool": f"braucht '{strong}'"}.get(
                    k, f"gehoert zu '{strong}'")
                return f"'{term}' {rolle} (staerkste graph-verbindung) — der eigentliche hebel liegt da."
        elif typ == "opportunity":
            bridge = d.get("bridge"); foc = (d.get("focus") or [None])[0]
            if bridge and foc:
                k = graph.kind_of(bridge)
                return {"person": f"'{bridge}' (person) kam bei aehnlichem schon mal vor — evtl. kann der bei '{foc}' helfen",
                        "tool": f"das prinzip/tool '{bridge}' koennte direkt auf '{foc}' passen",
                        }.get(k, f"die loesung aus '{bridge}' ist evtl. auf '{foc}' uebertragbar")
        elif typ == "dormant_revival":
            ent = d.get("entity")
            nbs = graph.neighbors(ent, k=3)
            ctx = ", ".join(n for n, _ in nbs[:2])
            if ctx:
                return f"'{ent}' hing damals mit {ctx} zusammen — da knuepfst du wahrscheinlich wieder an."
    except Exception:
        pass
    return ""

def run(focus_override=None):
    focus = focus_override or recent_focus()
    signals = []
    signals += detect_opportunities(focus)
    signals += detect_topic_spikes()
    signals += detect_dormant_revival()
    signals += detect_unusual_hours()
    for s in signals:                       # kausale hypothese an jedes signal haengen
        h = hypothesis(s, focus)
        if h:
            s["hypothesis"] = h
    signals.sort(key=lambda s: -s["score"])
    return {"focus": focus, "signals": signals}

if __name__ == "__main__":
    import json, sys
    fo = None
    if "--focus" in sys.argv:
        fo = sys.argv[sys.argv.index("--focus") + 1].split(",")
    print(json.dumps(run(focus_override=fo), indent=1, ensure_ascii=False))

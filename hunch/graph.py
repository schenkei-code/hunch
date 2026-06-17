# -*- coding: utf-8 -*-
"""Mini-Wissensgraph + Dot-Connecting — eigenbau, kein graphify/obsidian.
Entitaeten = nodes, co-occurrence = edges. dot_connect() findet verbindungen zwischen
aktuellem fokus und alten nodes („das prinzip aus projekt X passt auf dein aktuelles Y")."""
import re, collections, heapq
from . import store, baseline, config

# generische woerter die KEINE entitaet sind
NOISE = set(s.lower() for s in """
Users User Bild Video Problem Nachricht Ihre Nachrichten Foto Link Code Tool Plugin Datei Ordner
Hallo Danke Heute Morgen Abend Tag Woche Monat Jahr Stunde Minute Mail Email Account Status Update
Telegram Chat Channel Session Assistant System Prompt Test Beispiel Frage Antwort Info Dabei Damit
The This That What When Where Here There Just Like Make Done Next Step Run Build Okay
Bitte Ihnen Ihren Gerne Gruss Gruessen Gruesse Gruss Freundlichen Sehr Geehrte Geehrter Geehrten
Liebe Lieber Lieben Hallo Servus Wochenende Vormittag Nachmittag Mittag Mfg Lg Vielen Besten
Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag
Jetzt Lass Nicht Doch Klar Genau Sorry Passt Okay Gut Mach Schau Halt Eben Mal Bisschen
Dann Wenn Also Sobald Schon Noch Hier Dort Damit Dabei Sowas Etwas Irgendwas Alles Nichts
""".split() + ["grüße", "grüßen", "grüss", "für", "über"])

# entitaet = grossbuchstaben-start, multiword NUR ueber echte leerzeichen (NICHT ueber zeilenumbrueche
# -> sonst werden mail-signaturen wie "Gruessen\nMarkus" zu falschen entitaeten verklebt)
CAP = re.compile(r"\b([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9]{2,}(?:[^\S\r\n][A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9]+){0,2})\b")
MAX_PER_DOC = 6   # max entitaeten pro message fuer edges

# fuehrende generische woerter -> multiword ist keine echte entitaet
_BADLEAD = set("ihre ihr ihrem ihrer ihres ihren guten die der das den dem ein eine aber dabei damit "
               "diese dieser dieses mein dein sein unser jede jeder jedes alle viele neue gute erste "
               "letzte vielen diesen diesem alle paar nur noch schon dann wenn also sobald falls weil "
               "sehr lieben liebe lieber besten freundlichen".split())
_BADWORD = set("nachricht snapshot messages message dokument browser problem datei status update "
               "guten tag hallo danke ungelesen dank vielen erste letzte neue gesendet empfangen "
               "antwort frage info bild video foto link".split())

def extract_entities(text):
    out = []
    for m in CAP.findall(text or ""):
        ml = m.lower()
        if ml in NOISE or ml in config.USER_NAMES or len(m) < 4:
            continue
        toks = ml.split()
        if toks[0] in _BADLEAD:                  # 'Ihre Nachricht', 'Guten Tag'
            continue
        if all(t in _BADWORD or t in NOISE for t in toks):
            continue
        out.append(m)
    return out

def build_graph(limit_docs=6000, rebuild=False):
    store.init_db()
    if rebuild:
        store.clear_edges("co")
    # 1) globale entity-frequenz bestimmen (fuer salienz)
    freq = collections.Counter()
    docs = []
    with store.cursor() as con:
        # code-dateien (role='code') NICHT in die entity-extraktion -> kein variablen-namen-rauschen
        rows = con.execute("SELECT text FROM messages WHERE role IS NULL OR role != 'code' LIMIT ?", (limit_docs,)).fetchall()
        rows += con.execute("SELECT title AS text FROM events WHERE title IS NOT NULL LIMIT 2000").fetchall()
    for r in rows:
        ents = extract_entities(r["text"])
        if ents:
            docs.append(ents)
            freq.update(ents)
    # nur entitaeten mit freq>=3 als nodes
    keep = {e for e, c in freq.items() if c >= 3}
    ids = store.upsert_entities_bulk(keep, kind="topic")
    # 2) co-occurrence edges (top-MAX_PER_DOC salienteste pro doc)
    edges = collections.Counter()
    for ents in docs:
        sal = sorted(set(e for e in ents if e in keep), key=lambda x: -freq[x])[:MAX_PER_DOC]
        for i in range(len(sal)):
            for j in range(i + 1, len(sal)):
                a, b = sorted((ids[sal[i]], ids[sal[j]]))
                edges[(a, b)] += 1
    store.add_edges_bulk(((a, b, w) for (a, b), w in edges.items()), kind="co")
    return {"nodes": len(keep), "edges": len(edges), "docs": len(docs)}

def _eid(name):
    norm = name.strip().lower()
    with store.cursor() as con:
        r = con.execute("SELECT id FROM entities WHERE norm=?", (norm,)).fetchone()
        return r["id"] if r else None

def _name(eid):
    with store.cursor() as con:
        r = con.execute("SELECT name FROM entities WHERE id=?", (eid,)).fetchone()
        return r["name"] if r else None

def neighbors(name, k=8):
    eid = _eid(name)
    if not eid:
        return []
    with store.cursor() as con:
        rows = con.execute(
            "SELECT CASE WHEN src=? THEN dst ELSE src END nb, weight FROM edges "
            "WHERE (src=? OR dst=?) AND kind IN ('co','seed') ORDER BY weight DESC LIMIT ?",
            (eid, eid, eid, k)).fetchall()
    return [(_name(r["nb"]), r["weight"]) for r in rows]

def dot_connect(focus_names, k=6):
    """fuer aktuellen fokus: ranke verbundene NICHT-fokus-entitaeten = die 'denk-mal-an-X'-bruecken."""
    focus_ids = set(filter(None, (_eid(n) for n in focus_names)))
    if not focus_ids:
        return []
    score = collections.Counter()
    with store.cursor() as con:
        for fid in focus_ids:
            for r in con.execute(
                "SELECT CASE WHEN src=? THEN dst ELSE src END nb, weight FROM edges "
                "WHERE (src=? OR dst=?) AND kind IN ('co','seed')", (fid, fid, fid)):
                if r["nb"] not in focus_ids:
                    score[r["nb"]] += r["weight"]
    return [{"entity": _name(nb), "strength": round(w, 1)} for nb, w in score.most_common(k)]

def connect_path(a, b, max_hops=4):
    """kuerzeste verbindung zwischen zwei entitaeten (BFS) — 'wie haengt A mit B zusammen'."""
    sa, sb = _eid(a), _eid(b)
    if not sa or not sb:
        return None
    seen = {sa}
    q = [(sa, [sa])]
    while q:
        node, path = q.pop(0)
        if len(path) > max_hops:
            continue
        with store.cursor() as con:
            nbs = con.execute("SELECT CASE WHEN src=? THEN dst ELSE src END nb FROM edges WHERE src=? OR dst=?",
                              (node, node, node)).fetchall()
        for r in nbs:
            nb = r["nb"]
            if nb == sb:
                return [_name(x) for x in path + [nb]]
            if nb not in seen:
                seen.add(nb); q.append((nb, path + [nb]))
    return None

if __name__ == "__main__":
    import json, sys
    print("build:", json.dumps(build_graph()))
    # demo dot-connect auf dem ersten top-entity (falls vorhanden)
    s = store.get_profile("summary") or {}
    focus = (s.get("top_entities") or [])[:1]
    print("focus:", focus or "(noch keine entitaeten)")
    if focus:
        print("dot_connect:", json.dumps(dot_connect(focus), ensure_ascii=False))
        print("neighbors:", json.dumps(neighbors(focus[0]), ensure_ascii=False))

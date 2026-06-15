# -*- coding: utf-8 -*-
"""Pattern-of-Life Baseline — aggregiert events+messages zu einem lebendigen profil:
aktiv-stunden-rhythmus, app-nutzung, top-themen, bigrams, wiederkehrende entitaeten.
Lightweight (kein NLP-dep): tokenize + stopword-filter + frequenz + capitalized-detection."""
import re, time, math, collections, datetime
from . import store

STOP = set("""
der die das und oder aber wenn dann als auch noch nur schon sehr mehr viel mal so wie was wer wo
ich du er sie es wir ihr mich dich sich uns euch mir dir ihm ihr ihnen mein dein sein unser euer
ein eine einen einem einer eines kein keine nicht ist sind war waren bin bist hat habe haben hatte
wird werden wurde wuerde kann koennen muss muessen soll sollen will wollen darf duerfen mag
auf aus bei mit nach seit von vor zu zum zur im in an am um ueber unter durch fuer gegen ohne
des dem den dass weil damit ob doch mal eh halt grad gerade jetzt heute hier da dort
the a an and or but if then as also just only more very much how what who where this that these those
i you he she it we they me my your his her our their is are was were be been being have has had do does
of to in on at by for with from up out off over under into about can could should would will shall may
not no yes ok okay get got make made go going one two get like
http https www com de at org net html mp4 png jpg jpeg py md txt json com
""".split())

WORD = re.compile(r"[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9_\-]{2,}")
CAP = re.compile(r"\b([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9]{2,}(?:\s[A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9]+){0,2})\b")

def _tokens(text):
    return [w.lower() for w in WORD.findall(text or "") if w.lower() not in STOP and not w.isdigit()]

def build_active_hours():
    """rhythmus: echte watcher-events stark, ingested-messages schwach gewichtet."""
    hours_real = collections.Counter()
    hours_all = collections.Counter()
    with store.cursor() as con:
        for (ts,) in con.execute("SELECT ts FROM events WHERE source='watcher'"):
            hours_real[datetime.datetime.fromtimestamp(ts).hour] += 1
        for (ts,) in con.execute("SELECT ts FROM messages"):
            hours_all[datetime.datetime.fromtimestamp(ts).hour] += 1
    return {str(h): hours_real.get(h, 0) for h in range(24)}, {str(h): hours_all.get(h, 0) for h in range(24)}

def build_app_usage(limit=20):
    apps = collections.Counter()
    dwell = collections.Counter()
    with store.cursor() as con:
        for app, meta in con.execute("SELECT app, meta FROM events WHERE type='window' AND app IS NOT NULL"):
            apps[app] += 1
            try:
                import json
                d = json.loads(meta) if meta else {}
                dwell[app] += float(d.get("dwell_prev") or 0)
            except Exception:
                pass
    return [{"app": a, "switches": c, "dwell_s": round(dwell[a], 1)} for a, c in apps.most_common(limit)]

def build_topics(limit=40):
    uni = collections.Counter()
    bi = collections.Counter()
    with store.cursor() as con:
        # messages + event-titel
        rows = con.execute("SELECT text FROM messages").fetchall()
        rows += con.execute("SELECT title AS text FROM events WHERE title IS NOT NULL").fetchall()
    for r in rows:
        toks = _tokens(r["text"])
        uni.update(toks)
        for a, b in zip(toks, toks[1:]):
            bi[f"{a} {b}"] += 1
    top_uni = [{"term": t, "n": n} for t, n in uni.most_common(limit) if n >= 3]
    top_bi = [{"term": t, "n": n} for t, n in bi.most_common(limit) if n >= 3]
    return top_uni, top_bi

def build_entities(limit=40):
    from . import graph  # lazy -> vermeidet zirkular-import; nutzt den GEMEINSAMEN entity-filter
    caps = collections.Counter()
    with store.cursor() as con:
        rows = con.execute("SELECT text FROM messages").fetchall()
        rows += con.execute("SELECT title AS text FROM events WHERE title IS NOT NULL").fetchall()
    for r in rows:
        for m in graph.extract_entities(r["text"] or ""):
            caps[m] += 1
    return [{"name": k, "n": v} for k, v in caps.most_common(limit) if v >= 3]

def run():
    store.init_db()
    hr_real, hr_all = build_active_hours()
    apps = build_app_usage()
    uni, bi = build_topics()
    ents = build_entities()
    store.set_profile("active_hours_real", hr_real)
    store.set_profile("active_hours_all", hr_all)
    store.set_profile("app_usage", apps)
    store.set_profile("top_topics", uni)
    store.set_profile("top_bigrams", bi)
    store.set_profile("top_entities", ents)
    # menschlich lesbare zusammenfassung
    peak = sorted(hr_all.items(), key=lambda x: -x[1])[:3]
    summary = {
        "built": time.time(),
        "messages": store.counts()["messages"],
        "events": store.counts()["events"],
        "peak_hours": [h for h, _ in peak],
        "top_apps": [a["app"] for a in apps[:5]],
        "top_topics": [t["term"] for t in uni[:12]],
        "top_entities": [e["name"] for e in ents[:12]],
    }
    store.set_profile("summary", summary)
    return summary

if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=1, ensure_ascii=False))

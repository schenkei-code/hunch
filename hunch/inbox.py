# -*- coding: utf-8 -*-
"""Inbox — append-only beitrags-kanal fuer multi-agent. JEDER agent (oder ein fremder
prozess) wirft seine beobachtung ueber den user als EINE json-zeile in SEINE eigene
datei (INBOX_DIR/<agent>.jsonl). Getrennte dateien -> null schreib-konflikt zwischen agenten.
Der EINE brain liest alle dateien inkrementell (byte-offset gemerkt), dedupt und backt die
beobachtungen ins gemeinsame profil (als messages). So lernen alle aus dem was die anderen
ueber den user mitkriegen — ohne sich gegenseitig zu zerlegen.

Andere (auch nicht-python) agenten brauchen Hunch GAR NICHT zu importieren — sie haengen einfach
eine zeile an ihre datei an:  {"ts":..., "agent":"my-agent", "text":"...", "tags":[...]}
"""
import os, json, time, pathlib, hashlib
from . import config, store


def _agent_file(agent=None):
    agent = (agent or config.AGENT_NAME or "agent").strip().replace("/", "_")
    config.INBOX_DIR.mkdir(parents=True, exist_ok=True)
    return config.INBOX_DIR / f"{agent}.jsonl"


def note(text, tags=None, agent=None, meta=None):
    """append-only: EINE beobachtung in die eigene agent-datei schreiben. konflikt-frei."""
    if not text:
        return False
    rec = {"ts": time.time(), "agent": (agent or config.AGENT_NAME),
           "text": str(text)[:4000], "tags": tags or []}
    if meta:
        rec["meta"] = meta
    try:
        with open(_agent_file(agent), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


# ---------- brain-seite: alle agent-dateien inkrementell einsammeln ----------
def _offsets():
    return dict(store.get_profile("_inbox_offsets", {}) or {})


def _save_offsets(o):
    store.set_profile("_inbox_offsets", o)


def ingest():
    """liest aus allen INBOX_DIR/*.jsonl nur die NEUEN zeilen (ab gemerktem byte-offset),
    dedupt und legt sie als messages an (source='inbox:<agent>'). nur der brain ruft das."""
    store.init_db()
    d = config.INBOX_DIR
    if not d.exists():
        return {"files": 0, "inserted": 0}
    offsets = _offsets()
    rows, files_seen = [], 0
    for p in sorted(d.glob("*.jsonl")):
        files_seen += 1
        key = str(p)
        start = int(offsets.get(key, 0))
        try:
            size = p.stat().st_size
            if size < start:           # datei wurde rotiert/gekuerzt -> von vorn
                start = 0
            if size == start:
                continue
            with open(p, "r", encoding="utf-8", errors="ignore") as f:
                f.seek(start)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    text = (rec.get("text") or "").strip()
                    if not text:
                        continue
                    agent = rec.get("agent") or p.stem
                    ts = rec.get("ts") or time.time()
                    h = hashlib.sha1(f"inbox|{agent}|{text[:200]}".encode()).hexdigest()
                    rows.append({"text": text, "source": f"inbox:{agent}", "role": "agent_obs",
                                 "ts": ts, "hash": h,
                                 "meta": {"agent": agent, "tags": rec.get("tags") or []}})
                offsets[key] = p.stat().st_size
        except Exception:
            continue
    inserted = store.add_messages_bulk(rows) if rows else 0
    _save_offsets(offsets)
    store.set_profile("_last_inbox_ingest", time.time())
    return {"files": files_seen, "parsed": len(rows), "inserted": inserted}


if __name__ == "__main__":
    import sys
    a = sys.argv[1:]
    if a and a[0] == "note":
        ok = note(" ".join(a[1:]) or "test-beobachtung")
        print("note:", "ok" if ok else "fail", "->", _agent_file())
    else:
        print(json.dumps(ingest(), indent=1, ensure_ascii=False))

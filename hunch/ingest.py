# -*- coding: utf-8 -*-
"""Ingest — eigene archive read-only als startfutter in den store (messages).
Quellen kommen rein generisch aus config.INGEST_SOURCES (key = label, value = pfad).
Jede quelle ist entweder eine datei ODER ein verzeichnis (wird automatisch erkannt).
Self-contained, liest NUR, aendert nichts an den quellen. Dedupe via message-hash."""
import os, time, json, pathlib, hashlib
from . import config, store

MAX_CHUNKS = config.MAX_INGEST_CHUNKS   # globaler deckel (config-steuerbar: max_ingest_chunks)
CHUNK_MIN, CHUNK_MAX = 120, 1600

def _chunks(text):
    """markdown/text in sinnvolle haeppchen: paragraphen mergen bis ~CHUNK_MAX."""
    parts, buf = [], ""
    for para in (text or "").replace("\r", "").split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 2 <= CHUNK_MAX:
            buf = (buf + "\n\n" + para) if buf else para
        else:
            if len(buf) >= CHUNK_MIN:
                parts.append(buf)
            buf = para[:CHUNK_MAX]
    if len(buf) >= CHUNK_MIN:
        parts.append(buf)
    return parts

def _ingested_files():
    return set(store.get_profile("_ingested_files", []) or [])

def _mark_ingested(files):
    cur = _ingested_files()
    cur |= set(files)
    store.set_profile("_ingested_files", sorted(cur))

def ingest_file(path, source, role="context"):
    path = pathlib.Path(path)
    if not path.exists() or not path.is_file():
        return 0
    try:
        if path.stat().st_size > 2_000_000:   # >2MB skip
            return 0
        text = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return 0
    mt = path.stat().st_mtime
    n = 0
    for ch in _chunks(text):
        if store.add_message(ch, source=source, role=role, ts=mt,
                             meta={"file": path.name}):
            n += 1
    return n

def ingest_dir(d, source, exts=(".md", ".txt")):
    d = pathlib.Path(d)
    if not d.exists():
        return 0, 0
    done = _ingested_files()
    n_files = n_chunks = 0
    total_now = store.counts()["messages"]
    for p in sorted(d.rglob("*")):
        if total_now + n_chunks > MAX_CHUNKS:
            break
        if p.suffix.lower() not in exts or not p.is_file():
            continue
        key = str(p)
        if key in done:
            continue
        c = ingest_file(p, source=source)
        if c:
            n_files += 1; n_chunks += c
            done.add(key)
    return n_files, n_chunks

def run():
    """generisch ueber config.INGEST_SOURCES: jeder eintrag {label: pfad}. pfad zeigt auf
    eine datei (-> ingest_file) oder ein verzeichnis (-> ingest_dir, rglob md/txt).
    keine festen quell-namen -> jeder user konfiguriert eigene quellen frei."""
    store.init_db()
    report = {}
    allfiles = set()
    for label, path in (config.INGEST_SOURCES or {}).items():
        p = pathlib.Path(path)
        if not p.exists():
            report[f"{label}_chunks"] = 0
            continue
        if p.is_file():
            # einzeldatei (z.b. ein profil) -> als zusammenhaengende quelle, rolle 'profile'
            report[f"{label}_chunks"] = ingest_file(p, source=label, role="profile")
            allfiles.add(str(p))
        else:
            f, c = ingest_dir(p, source=label)
            report[f"{label}_files"], report[f"{label}_chunks"] = f, c
            for q in p.rglob("*"):
                if q.suffix.lower() in (".md", ".txt") and q.is_file():
                    allfiles.add(str(q))
    _mark_ingested(allfiles)
    store.set_profile("_last_ingest", time.time())
    report["total_messages"] = store.counts()["messages"]
    return report

if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))

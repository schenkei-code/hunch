# -*- coding: utf-8 -*-
"""Ingest — bestehende archive read-only als startfutter in den store (messages).
Quellen: dominik.md (profil), memory/*.md, all-history (digests + txt). Self-contained,
liest NUR, aendert nichts an den quellen. Dedupe via message-hash, schon-ingested via meta."""
import os, time, json, pathlib, hashlib
from . import config, store

MAX_CHUNKS = 8000          # globaler deckel
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
    store.init_db()
    report = {}
    # 1) dominik.md — kern-profil (eigene quelle, hoch gewichtet)
    dp = config.INGEST_SOURCES["dominik_profile"]
    report["dominik_profile_chunks"] = ingest_file(dp, source="dominik_profile", role="profile")
    if pathlib.Path(dp).exists():
        _mark_ingested([str(dp)])
    # 2) memory/*.md
    f, c = ingest_dir(config.INGEST_SOURCES["memory_dir"], source="memory")
    report["memory_files"], report["memory_chunks"] = f, c
    # 3) all-history (digests + txt)
    f, c = ingest_dir(config.INGEST_SOURCES["all_history"], source="all_history")
    report["history_files"], report["history_chunks"] = f, c
    # markiere die dirs als ingested (file-level schon in ingest_dir gesammelt -> persistieren)
    allfiles = set()
    for d in (config.INGEST_SOURCES["memory_dir"], config.INGEST_SOURCES["all_history"]):
        dd = pathlib.Path(d)
        if dd.exists():
            for p in dd.rglob("*"):
                if p.suffix.lower() in (".md", ".txt") and p.is_file():
                    allfiles.add(str(p))
    _mark_ingested(allfiles)
    store.set_profile("_last_ingest", time.time())
    report["total_messages"] = store.counts()["messages"]
    return report

if __name__ == "__main__":
    print(json.dumps(run(), indent=1, ensure_ascii=False))

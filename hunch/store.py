# -*- coding: utf-8 -*-
"""SQLite-Store fuer Hunch. WAL-mode, kurze transaktionen, retry-safe.
Tabellen: events, messages, entities, edges, profile, nudges, meta.
Flexible JSON-felder (`meta`) damit das schema mitwaechst ohne migration."""
import sqlite3, json, time, contextlib
from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,              -- unix epoch
  type TEXT NOT NULL,            -- window|clipboard|file|browser|app_switch|...
  source TEXT,                   -- watcher|ingest|...
  app TEXT,                      -- prozess/exe
  title TEXT,                    -- fenstertitel / url-titel
  path TEXT,                     -- dateipfad / url
  text TEXT,                     -- clipboard-text / snippet
  meta TEXT                      -- json
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS ix_events_type ON events(type);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  source TEXT,                   -- telegram|whatsapp|session|profile|...
  role TEXT,                     -- dominik|assistant|other
  text TEXT,
  meta TEXT,
  hash TEXT UNIQUE               -- dedupe
);
CREATE INDEX IF NOT EXISTS ix_messages_ts ON messages(ts);

CREATE TABLE IF NOT EXISTS entities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT,                     -- project|person|topic|tool|app|file
  norm TEXT UNIQUE,              -- normalisierter key
  first_seen REAL,
  last_seen REAL,
  count INTEGER DEFAULT 0,
  meta TEXT
);

CREATE TABLE IF NOT EXISTS edges (
  src INTEGER NOT NULL,
  dst INTEGER NOT NULL,
  kind TEXT DEFAULT 'co',        -- co-occurrence|...
  weight REAL DEFAULT 0,
  last_seen REAL,
  PRIMARY KEY (src, dst, kind)
);

CREATE TABLE IF NOT EXISTS profile (
  key TEXT PRIMARY KEY,
  value TEXT,                    -- json
  updated REAL
);

CREATE TABLE IF NOT EXISTS nudges (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  kind TEXT,
  text TEXT,
  score REAL,
  sent INTEGER DEFAULT 0,
  meta TEXT
);

CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT
);
"""

def connect():
    con = sqlite3.connect(str(config.DB_PATH), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA busy_timeout=30000;")
    return con

def init_db():
    con = connect()
    with con:
        con.executescript(SCHEMA)
    con.close()

@contextlib.contextmanager
def cursor():
    con = connect()
    try:
        with con:
            yield con
    finally:
        con.close()

# ---------- events ----------
def add_event(type, source="watcher", app=None, title=None, path=None, text=None, meta=None, ts=None):
    with cursor() as con:
        con.execute(
            "INSERT INTO events(ts,type,source,app,title,path,text,meta) VALUES(?,?,?,?,?,?,?,?)",
            (ts or time.time(), type, source, app, title, path, text,
             json.dumps(meta, ensure_ascii=False) if meta else None))

# ---------- messages (dedupe via hash) ----------
def add_message(text, source, role="dominik", ts=None, meta=None, hash=None):
    import hashlib
    h = hash or hashlib.sha1(f"{source}|{role}|{(text or '')[:400]}".encode("utf-8")).hexdigest()
    try:
        with cursor() as con:
            con.execute(
                "INSERT OR IGNORE INTO messages(ts,source,role,text,meta,hash) VALUES(?,?,?,?,?,?)",
                (ts or time.time(), source, role, text,
                 json.dumps(meta, ensure_ascii=False) if meta else None, h))
            return con.total_changes
    except Exception:
        return 0

# ---------- entities + edges ----------
def upsert_entity(name, kind="topic", ts=None):
    norm = (name or "").strip().lower()
    if not norm:
        return None
    now = ts or time.time()
    with cursor() as con:
        row = con.execute("SELECT id,count FROM entities WHERE norm=?", (norm,)).fetchone()
        if row:
            con.execute("UPDATE entities SET last_seen=?, count=count+1 WHERE id=?", (now, row["id"]))
            return row["id"]
        cur = con.execute(
            "INSERT INTO entities(name,kind,norm,first_seen,last_seen,count) VALUES(?,?,?,?,?,1)",
            (name, kind, norm, now, now))
        return cur.lastrowid

def upsert_entities_bulk(names, kind="topic", ts=None):
    """viele entitaeten in EINER transaktion anlegen/auffrischen -> schnell beim rebuild.
    return {name: id}."""
    now = ts or time.time()
    items = []
    for n in names:
        norm = (n or "").strip().lower()
        if norm:
            items.append((n, kind, norm, now, now))
    if not items:
        return {}
    with cursor() as con:
        con.executemany(
            "INSERT INTO entities(name,kind,norm,first_seen,last_seen,count) VALUES(?,?,?,?,?,1) "
            "ON CONFLICT(norm) DO UPDATE SET last_seen=excluded.last_seen, count=count+1", items)
        norms = [it[2] for it in items]
        out = {}
        # in chunks lesen (sqlite param-limit)
        for i in range(0, len(norms), 800):
            chunk = norms[i:i+800]
            q = "SELECT id,name,norm FROM entities WHERE norm IN (%s)" % ",".join("?" * len(chunk))
            for r in con.execute(q, chunk):
                out[r["norm"]] = r["id"]
    # map name->id ueber norm
    return {n: out.get((n or "").strip().lower()) for n in names}

def add_edge(src, dst, kind="co", w=1.0, ts=None):
    if not src or not dst or src == dst:
        return
    a, b = sorted((src, dst))
    now = ts or time.time()
    with cursor() as con:
        con.execute(
            "INSERT INTO edges(src,dst,kind,weight,last_seen) VALUES(?,?,?,?,?) "
            "ON CONFLICT(src,dst,kind) DO UPDATE SET weight=weight+?, last_seen=?",
            (a, b, kind, w, now, w, now))

def add_edges_bulk(triples, kind="co", ts=None):
    """triples = iterable von (src,dst,weight). EINE transaktion -> schnell beim graph-rebuild."""
    now = ts or time.time()
    rows = []
    for src, dst, w in triples:
        if not src or not dst or src == dst:
            continue
        a, b = sorted((src, dst))
        rows.append((a, b, kind, float(w), now, float(w), now))
    if not rows:
        return 0
    with cursor() as con:
        con.executemany(
            "INSERT INTO edges(src,dst,kind,weight,last_seen) VALUES(?,?,?,?,?) "
            "ON CONFLICT(src,dst,kind) DO UPDATE SET weight=weight+?, last_seen=?", rows)
    return len(rows)

def clear_edges(kind=None):
    with cursor() as con:
        if kind:
            con.execute("DELETE FROM edges WHERE kind=?", (kind,))
        else:
            con.execute("DELETE FROM edges")

# ---------- profile ----------
def set_profile(key, value):
    with cursor() as con:
        con.execute("INSERT INTO profile(key,value,updated) VALUES(?,?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value=?, updated=?",
                    (key, json.dumps(value, ensure_ascii=False), time.time(),
                     json.dumps(value, ensure_ascii=False), time.time()))

def get_profile(key, default=None):
    with cursor() as con:
        row = con.execute("SELECT value FROM profile WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

# ---------- nudges ----------
def add_nudge(text, kind, score, sent=0, meta=None):
    with cursor() as con:
        cur = con.execute("INSERT INTO nudges(ts,kind,text,score,sent,meta) VALUES(?,?,?,?,?,?)",
                          (time.time(), kind, text, score, sent,
                           json.dumps(meta, ensure_ascii=False) if meta else None))
        return cur.lastrowid

def last_nudge_ts():
    with cursor() as con:
        row = con.execute("SELECT MAX(ts) t FROM nudges WHERE sent=1").fetchone()
        return row["t"] or 0

def counts():
    with cursor() as con:
        out = {}
        for t in ("events", "messages", "entities", "edges", "nudges"):
            out[t] = con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
        return out

if __name__ == "__main__":
    init_db()
    print("init ok ->", config.DB_PATH)
    print("counts:", counts())

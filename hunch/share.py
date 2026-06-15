# -*- coding: utf-8 -*-
"""Share — das „ein schreiber, viele leser"-fundament fuer multi-agent / multi-device.
Der EINE Hunch-brain publiziert sein profil in SHARE_DIR (markdown FÜR menschen/agenten +
strukturiertes json FÜR agenten). ALLE anderen agenten (auf windows ODER WSL) LESEN das nur —
reines lesen kann nie kollidieren, und weil nur ein brain schreibt gibt's keine db-races.
Der brain-lock (cooperative, heartbeat-basiert) stellt sicher, dass NIE zwei brains gleichzeitig
laufen: wer kein frisches fremd-lock sieht wird brain, sonst reader."""
import os, json, time, socket, pathlib
from . import config, store, detect, graph, bridge

LOCK = "brain.lock"
PROFILE_MD = "hunch_profile.md"      # menschen-/agenten-lesbar
PROFILE_JSON = "hunch_profile.json"  # strukturiert fuer agenten


def _host():
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


# ---------- brain-lock (cooperative, multi-device-sicher) ----------
def _lock_path():
    config.SHARE_DIR.mkdir(parents=True, exist_ok=True)
    return config.SHARE_DIR / LOCK


def read_lock():
    p = _lock_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _own_id():
    return f"{config.AGENT_NAME}@{_host()}:{os.getpid()}"


def lock_is_fresh(lock):
    return bool(lock) and (time.time() - lock.get("ts", 0) < config.BRAIN_LOCK_TTL_SEC)


def foreign_brain_active():
    """laeuft schon ein ANDERES frisches brain (anderer owner)?"""
    lock = read_lock()
    return lock_is_fresh(lock) and lock.get("owner") != _own_id()


def acquire_or_refresh_lock():
    """schreibt/erneuert das eigene brain-lock. return True wenn wir der brain sind."""
    if foreign_brain_active():
        return False
    try:
        _lock_path().write_text(json.dumps(
            {"owner": _own_id(), "agent": config.AGENT_NAME, "host": _host(),
             "pid": os.getpid(), "ts": time.time()}, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def release_lock():
    lock = read_lock()
    if lock and lock.get("owner") == _own_id():
        try:
            _lock_path().unlink()
        except Exception:
            pass


def resolve_role():
    """brain | reader — laut config.HUNCH_ROLE, 'auto' entscheidet per lock."""
    r = config.HUNCH_ROLE
    if r == "brain":
        return "brain"
    if r == "reader":
        return "reader"
    return "reader" if foreign_brain_active() else "brain"


# ---------- profil publizieren (nur der brain) ----------
def build_profile_json():
    summ = store.get_profile("summary") or {}
    det = detect.run()
    ents = summ.get("top_entities", [])[:12]
    highlights = []
    for e in ents[:6]:
        nb = graph.neighbors(e, k=1)
        if nb and nb[0][0]:
            highlights.append([e, nb[0][0], nb[0][1]])
    # jüngste stimmung (emotion-proxy) aus session-messages
    mood = {}
    try:
        with store.cursor() as con:
            rows = con.execute(
                "SELECT meta FROM messages WHERE source='session' AND role='user' "
                "AND json_extract(meta,'$.auto') IS NULL AND json_extract(meta,'$.emotion') IS NOT NULL "
                "ORDER BY ts DESC LIMIT 200").fetchall()
        from collections import Counter
        c = Counter(json.loads(r["meta"]).get("emotion") for r in rows)
        mood = dict(c.most_common())
    except Exception:
        pass
    return {
        "updated": time.time(),
        "counts": store.counts(),
        "peak_hours": summ.get("peak_hours"),
        "top_apps": summ.get("top_apps", [])[:8],
        "top_topics": summ.get("top_topics", [])[:15],
        "top_entities": ents,
        "graph_highlights": highlights,
        "recent_focus": det.get("focus", [])[:10],
        "signals": [{"type": s["type"], "score": s["score"], "text": s["text"]}
                    for s in det.get("signals", [])[:6]],
        "recent_mood": mood,
        "source_agent": config.AGENT_NAME,
        "host": _host(),
    }


def publish():
    """schreibt profil als markdown + json nach SHARE_DIR. nur sinnvoll vom brain aufzurufen."""
    try:
        config.SHARE_DIR.mkdir(parents=True, exist_ok=True)
        (config.SHARE_DIR / PROFILE_MD).write_text(bridge.build_markdown(), encoding="utf-8")
        (config.SHARE_DIR / PROFILE_JSON).write_text(
            json.dumps(build_profile_json(), ensure_ascii=False, indent=1), encoding="utf-8")
        return True, str(config.SHARE_DIR)
    except Exception as e:
        return False, str(e)[:120]


# ---------- leser-seite (jeder agent) ----------
def read_profile():
    """von JEDEM agenten aufrufbar (auch ausserhalb python via die json-datei direkt lesen)."""
    p = config.SHARE_DIR / PROFILE_JSON
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


if __name__ == "__main__":
    print("role:", resolve_role())
    print("lock:", read_lock())
    ok, info = publish()
    print("publish:", "OK ->" if ok else "FAIL:", info)

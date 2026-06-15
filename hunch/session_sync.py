# -*- coding: utf-8 -*-
"""Session-Sync — zieht ALLE bisherigen Claude-Code-Sessions wort-fuer-wort in den store.
Quelle: die JSONL-transcripts die Claude Code selbst pro session schreibt
(~/.claude/projects/<projektordner>/<uuid>.jsonl). Jede zeile = ein event; relevant sind
'user' (mensch tippt) und 'assistant' (antwort). Pro nachricht wird festgehalten:
  - text (wort fuer wort)            - timestamp (echte uhrzeit)
  - rolle (user|assistant)           - antwortzeit (gap zur vorherigen nachricht)
  - antwort-art (frage|ansage|tool|kurz|lang)
  - emotion-proxy (emotion.py: ton/erregung/polaritaet)  - session-id + projekt

Read-only auf die transcripts. Idempotent: dedupe via stabilem hash je (session,uuid).
Generisch & datenfrei — default-quelle ~/.claude/projects gilt fuer JEDEN Claude-Code-user.
Inkrementell: gemerkt wird die groesste mtime je datei -> beim naechsten lauf nur neues."""
import os, re, json, time, pathlib, hashlib, datetime
from . import config, store, emotion

# zeilen die KEIN echtes menschliches gespraech sind (hook-injektionen, tool-output, befehle,
# system-summaries). Nach dem unwrap geprueft.
_NOISE_MARKERS = (
    "<command-name>", "<command-message>", "<command-args>", "<local-command-stdout>",
    "<system-reminder>", "caveat: the messages below", "[request interrupted",
    "this session was opened", "<bash-input>", "<bash-stdout>",
    "<task-notification>", "this session is being continued",
    "continue the conversation from where it left off", "<session-start",
    "the summary below covers", "api error", "<user-prompt-submit-hook>",
    "stop hook feedback", "hook feedback:", "posttooluse", "pretooluse",
)
# bekannte bridge-wrapper (z.b. telegram-plugin) -> der ECHTE menschliche text steckt drin.
_CHANNEL_RE = re.compile(r"<channel\b[^>]*>(.*?)</channel>", re.DOTALL | re.IGNORECASE)
MAX_TEXT = 8000          # pro nachricht kappen (riesige tool-dumps)
MIN_TEXT = 2            # leeres/winziges ignorieren


# automatisierte/injizierte turns (cron, agent-SDK, system) — KEIN echtes gespraech.
# entrypoint traegt durchgehend (auch alte sessions), promptSource nur in neuen.
_AUTO_ENTRY = {"sdk-cli", "sdk-py"}
_AUTO_SRC = {"sdk", "system", "queued"}
# slash-command-/agent-prompt-bodies die als user-turn auftauchen (templated, nicht getippt)
# tunbare liste (erweiterbar) — slash-command-/loop-/agent-prompt-koepfe
_TEMPLATE_HEADS = ("review this change", "help me fix the issues", "du bist der automatische",
                   "you are the", "du bist 'hunch'", "# resume session", "analyze the following",
                   "du arbeitest ab jetzt", "you are now working", "du bist 'machine'",
                   "you are a", "you are an", "your task is")


def _is_automated(o, text):
    if o.get("entrypoint") in _AUTO_ENTRY or o.get("promptSource") in _AUTO_SRC:
        return True
    low = (text or "").lstrip().lower()
    if low.startswith("# ") or "$arguments" in low:
        return True
    return any(low.startswith(h) for h in _TEMPLATE_HEADS)


def _unwrap(text):
    """packt bekannte bridge-wrapper aus (z.b. <channel>…</channel> vom telegram-plugin),
    sodass der reine menschliche text uebrig bleibt. ohne wrapper: unveraendert zurueck."""
    if not text:
        return text
    m = _CHANNEL_RE.search(text)
    if m:
        inner = m.group(1).strip()
        # attachment-platzhalter wie '(voice message)' behalten ist ok, aber leeres droppen
        return inner
    return text.strip()


def _iso_to_ts(s):
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _extract_text(message):
    """holt den reinen gespraechs-text aus message.content (string ODER block-liste).
    tool_result/tool_use/image werden NICHT als gespraech gewertet -> (text, art_flags)."""
    if message is None:
        return "", set()
    content = message.get("content")
    flags = set()
    if isinstance(content, str):
        return content.strip(), flags
    parts = []
    if isinstance(content, list):
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                parts.append((b.get("text") or "").strip())
            elif bt == "tool_use":
                flags.add("tool")
            elif bt == "tool_result":
                flags.add("tool_result")
            elif bt in ("image", "document"):
                flags.add("attachment")
    return "\n".join(p for p in parts if p).strip(), flags


def _is_noise(text):
    low = text.lower()
    return any(m in low for m in _NOISE_MARKERS)


def _answer_kind(text, flags, role):
    """grobe antwort-art."""
    if "tool_result" in flags and not text:
        return "tool_result"
    n = len(text.split())
    base = []
    if role == "user":
        if text.rstrip().endswith("?") or text.lower().split(" ")[:1] in (
                ["wie"], ["was"], ["warum"], ["wieso"], ["kannst"], ["geht"]):
            base.append("frage")
        else:
            base.append("ansage")
    if "tool" in flags:
        base.append("tool")
    base.append("kurz" if n <= 12 else ("lang" if n > 120 else "mittel"))
    return "+".join(base)


def _session_files(roots):
    files = []
    for root in roots:
        p = pathlib.Path(os.path.expanduser(str(root)))
        if not p.exists():
            continue
        if p.is_file() and p.suffix == ".jsonl":
            files.append(p)
        else:
            files.extend(sorted(p.rglob("*.jsonl")))
    return files


def _seen_state():
    return dict(store.get_profile("_session_sync_state", {}) or {})


def _save_state(state):
    store.set_profile("_session_sync_state", state)


def sync_file(path, state, only_new=True):
    """parst EINE session-jsonl -> liste von message-rows (fuer add_messages_bulk).
    setzt response-time (gap zur vorherigen gespraechs-nachricht) + emotion."""
    path = pathlib.Path(path)
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except Exception:
        return [], state
    if only_new and state.get(key, {}).get("mtime") == mtime:
        return [], state      # unveraendert seit letztem sync

    rows = []
    prev_ts = None            # fuer antwortzeit
    sid = path.stem
    project = path.parent.name
    try:
        fh = path.open(encoding="utf-8", errors="ignore")
    except Exception:
        return [], state
    with fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            typ = o.get("type")
            if typ not in ("user", "assistant"):
                continue
            if o.get("isSidechain"):     # sub-agent-konversation (Task/Agent-tool), kein haupt-gespraech
                continue
            text, flags = _extract_text(o.get("message"))
            text = _unwrap(text)                      # bridge-wrapper (telegram etc.) auspacken
            ts = _iso_to_ts(o.get("timestamp"))
            if text and len(text) > MAX_TEXT:
                text = text[:MAX_TEXT]
            # nur echtes gespraech: hat text, kein noise, keine reine tool_result-zeile
            if not text or len(text) < MIN_TEXT or _is_noise(text):
                # tool_result/leer trotzdem fuer den rhythmus zaehlen? nein -> ueberspringen
                continue
            role = "user" if typ == "user" else "assistant"
            auto = _is_automated(o, text) if role == "user" else False
            resp_dt = round(ts - prev_ts, 1) if (ts and prev_ts) else None
            prev_ts = ts or prev_ts
            # emotion nur fuer ECHTES menschliches gespraech (kein cron/agent/command-body)
            emo = emotion.emotion(text, role) if (role == "user" and not auto) else None
            uuid = o.get("uuid") or hashlib.sha1((text[:120]).encode()).hexdigest()
            h = hashlib.sha1(f"session|{sid}|{uuid}".encode()).hexdigest()
            meta = {
                "session": sid,
                "project": project,
                "kind": _answer_kind(text, flags, role),
                "response_time_s": resp_dt,
                "entry": o.get("entrypoint"),
            }
            if auto:
                meta["auto"] = True
            if emo:
                meta["emotion"] = emo["label"]
                meta["polarity"] = emo["polarity"]
                meta["arousal"] = emo["arousal"]
                if emo["signals"]:
                    meta["emo_signals"] = emo["signals"]
            rows.append({"text": text, "source": "session", "role": role,
                         "ts": ts or mtime, "meta": meta, "hash": h})
    state[key] = {"mtime": mtime, "rows": len(rows), "synced": time.time()}
    return rows, state


def run(only_new=True, roots=None, batch=2000):
    """synct alle sessions. only_new=True -> nur seit letztem lauf veraenderte dateien."""
    store.init_db()
    roots = roots or config.SESSION_SOURCES
    files = _session_files(roots)
    state = _seen_state()
    total_new = total_files = total_rows = 0
    buf = []
    for f in files:
        rows, state = sync_file(f, state, only_new=only_new)
        if rows:
            total_files += 1
            total_rows += len(rows)
            buf.extend(rows)
            if len(buf) >= batch:
                total_new += store.add_messages_bulk(buf)
                buf = []
    if buf:
        total_new += store.add_messages_bulk(buf)
    _save_state(state)
    store.set_profile("_last_session_sync", time.time())
    return {"files_scanned": len(files), "files_with_new": total_files,
            "messages_parsed": total_rows, "messages_inserted": total_new}


if __name__ == "__main__":
    import sys
    full = "--full" in sys.argv      # alles neu (ignoriert state)
    print(json.dumps(run(only_new=not full), indent=1, ensure_ascii=False))

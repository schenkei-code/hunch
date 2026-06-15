# -*- coding: utf-8 -*-
"""Zentrale Konfiguration. KEINE secrets/persoenlichen werte im code:
laedt aus env-variablen ODER einer lokalen, gitignoreten config.local.json.
Veroeffentlichbar — die echten werte liegen NUR in config.local.json (nicht im repo)."""
import os, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "hunch.db"

# ---- lokale config (gitignored) als quelle fuer alles persoenliche ----
def _load_local():
    p = ROOT / "config.local.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}
_L = _load_local()

def _get(key, env, default=None):
    v = os.environ.get(env)
    if v is not None and v != "":
        return v
    if key in _L and _L[key] not in (None, ""):
        return _L[key]
    return default

def _expand(p):
    return os.path.expanduser(p) if p else p

# ---- Telegram (nudge-kanal) ----
def _fallback_dotenv_token():
    # optionaler fallback: claude-telegram-plugin .env (existiert evtl. auf dem rechner)
    envp = pathlib.Path(os.path.expanduser("~")) / ".claude" / "channels" / "telegram" / ".env"
    try:
        for line in envp.read_text(encoding="utf-8").splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip()
    except Exception:
        pass
    return None

BOT_TOKEN = _get("bot_token", "MACHINE_BOT_TOKEN") or _fallback_dotenv_token()
CHAT_ID = _get("chat_id", "MACHINE_CHAT_ID")            # KEIN persoenlicher default
USER_DESC = _get("user_desc", "MACHINE_USER_DESC", "der user")  # fuer den nudge-stil

# ---- watcher ----
WATCH_INTERVAL_SEC = int(_get("watch_interval", "MACHINE_WATCH_INTERVAL", 4))
WATCH_CLIPBOARD = str(_get("watch_clipboard", "MACHINE_WATCH_CLIPBOARD", "1")) not in ("0", "false")
WATCH_BROWSER_HISTORY = str(_get("watch_browser", "MACHINE_WATCH_BROWSER", "1")) not in ("0", "false")
BROWSER_HISTORY_EVERY_SEC = 300

# ---- ingest quellen (read-only startfutter; default leer -> user konfiguriert) ----
INGEST_SOURCES = {k: pathlib.Path(_expand(v)) for k, v in (_L.get("ingest_sources") or {}).items()}

# ---- brain / nudge ----
NUDGE_MIN_SCORE = float(_get("nudge_min_score", "MACHINE_NUDGE_MIN_SCORE", 0.62))
_qh = _L.get("quiet_hours") or [1, 8]
NUDGE_QUIET_HOURS = (int(_qh[0]), int(_qh[1]))
NUDGE_MIN_GAP_MIN = int(_get("nudge_min_gap_min", "MACHINE_NUDGE_GAP", 90))
CLAUDE_BIN = _get("claude_bin", "MACHINE_CLAUDE_BIN", "claude")
NUDGE_MODEL = _get("nudge_model", "MACHINE_NUDGE_MODEL", "claude-sonnet-4-6")
# LLM-formulierung der nudges via `claude -p`. Default AUS = 100% gratis/lokal (template-nudges).
# Nur einschalten wenn du budget/credit hast (claude -p kann pay-as-you-go kosten).
NUDGE_USE_LLM = str(_get("nudge_use_llm", "HUNCH_NUDGE_USE_LLM", "0")) in ("1", "true", "True")

# ---- runtime / scheduler ----
BRAIN_EVERY_MIN = int(_get("brain_every_min", "MACHINE_BRAIN_EVERY", 30))
BASELINE_EVERY_MIN = int(_get("baseline_every_min", "MACHINE_BASELINE_EVERY", 180))
PY_BIN = _get("py_bin", "MACHINE_PY", None)

# ---- bridge: optionaler export von Hunch's erkenntnissen in ein externes memory (markdown) ----
# nur gesetzt wenn in config.local.json/env vorhanden -> public repo bleibt clean.
_mep = _get("memory_export_path", "HUNCH_MEMORY_EXPORT", None)
MEMORY_EXPORT_PATH = pathlib.Path(_expand(_mep)) if _mep else None

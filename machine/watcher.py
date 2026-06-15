# -*- coding: utf-8 -*-
"""Watcher — sammelt volle PC-signale lokal in den store.
Signale: aktives fenster (+prozess), app-switches, clipboard-aenderungen, geoeffnete dateien
(via fenstertitel + Windows Recent), browser-historie (Chrome/Edge). Nur bei CHANGE loggen.
Robust: jede quelle in try/except, eine kaputte quelle killt den loop nicht.
Modi: `python -m machine.watcher --seconds N` (laeuft N sek, fuer test) | `--once` | (default: dauerloop)."""
import sys, time, os, shutil, sqlite3, glob, tempfile, pathlib
from . import config, store

try:
    import win32gui, win32process
    import psutil
    _WIN = True
except Exception:
    _WIN = False

# ---------- aktives fenster ----------
def active_window():
    if not _WIN:
        return (None, None)
    try:
        hwnd = win32gui.GetForegroundWindow()
        title = win32gui.GetWindowText(hwnd) or ""
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        app = None
        try:
            app = psutil.Process(pid).name()
        except Exception:
            app = f"pid:{pid}"
        return (app, title)
    except Exception:
        return (None, None)

# ---------- clipboard ----------
def clipboard_text():
    if not _WIN:
        return None
    try:
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            import win32con
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            else:
                data = None
        finally:
            win32clipboard.CloseClipboard()
        if data:
            return data[:4000]  # cappen
    except Exception:
        return None
    return None

# ---------- dateipfade aus fenstertitel ----------
import re
_PATH_RE = re.compile(r"[A-Za-z]:\\[^\t\n\r*?\"<>|]+\.[A-Za-z0-9]{1,6}")
def paths_in_title(title):
    if not title:
        return []
    return _PATH_RE.findall(title)

# ---------- Windows Recent (geoeffnete dateien) ----------
def recent_files(since_ts):
    out = []
    recent = pathlib.Path(os.path.expanduser("~")) / "AppData/Roaming/Microsoft/Windows/Recent"
    try:
        for p in recent.glob("*.lnk"):
            try:
                m = p.stat().st_mtime
                if m > since_ts:
                    out.append((p.stem, m))
            except Exception:
                pass
    except Exception:
        pass
    return out

# ---------- browser-historie (Chrome/Edge) ----------
_BROWSERS = {
    "chrome": "~/AppData/Local/Google/Chrome/User Data/*/History",
    "edge":   "~/AppData/Local/Microsoft/Edge/User Data/*/History",
}
def browser_history(since_ts):
    rows = []
    for name, pat in _BROWSERS.items():
        for hist in glob.glob(os.path.expanduser(pat)):
            try:
                tmp = os.path.join(tempfile.gettempdir(), f"_mh_{name}_{os.getpid()}.db")
                shutil.copy2(hist, tmp)  # kopieren, weil original gelockt waehrend browser laeuft
                con = sqlite3.connect(tmp)
                # chrome-zeit = mikrosek seit 1601-01-01; cutoff umrechnen
                chrome_cut = int((since_ts + 11644473600) * 1_000_000)
                for url, title, vt in con.execute(
                    "SELECT url,title,last_visit_time FROM urls WHERE last_visit_time>? ORDER BY last_visit_time DESC LIMIT 200",
                    (chrome_cut,)):
                    epoch = vt / 1_000_000 - 11644473600
                    rows.append((name, url, title, epoch))
                con.close()
                try: os.remove(tmp)
                except Exception: pass
            except Exception:
                pass
    return rows

# ---------- ein sweep ----------
_state = {"last_win": None, "last_clip": None, "win_since": None, "last_browser": 0, "last_recent": 0}

def sweep():
    n = 0
    now = time.time()
    # aktives fenster — nur bei change
    try:
        app, title = active_window()
        key = f"{app}|{title}"
        if app and key != _state["last_win"]:
            dwell = (now - _state["win_since"]) if _state["win_since"] else None
            store.add_event("window", app=app, title=title,
                            meta={"dwell_prev": round(dwell, 1)} if dwell else None)
            for pth in paths_in_title(title):
                store.add_event("file", app=app, path=pth, title=title, source="watcher")
                n += 1
            _state["last_win"] = key
            _state["win_since"] = now
            n += 1
    except Exception:
        pass
    # clipboard — nur bei change
    try:
        if config.WATCH_CLIPBOARD:
            clip = clipboard_text()
            if clip and clip != _state["last_clip"]:
                store.add_event("clipboard", text=clip)
                _state["last_clip"] = clip
                n += 1
    except Exception:
        pass
    # recent files (alle ~30s)
    try:
        if now - _state["last_recent"] > 30:
            for stem, m in recent_files(_state["last_recent"] or now - 60):
                store.add_event("file", path=stem, source="recent", ts=m)
                n += 1
            _state["last_recent"] = now
    except Exception:
        pass
    # browser-historie (alle BROWSER_HISTORY_EVERY_SEC)
    try:
        if config.WATCH_BROWSER_HISTORY and now - _state["last_browser"] > config.BROWSER_HISTORY_EVERY_SEC:
            for br, url, title, epoch in browser_history(_state["last_browser"] or now - 3600):
                store.add_event("browser", app=br, path=url, title=title, ts=epoch)
                n += 1
            _state["last_browser"] = now
    except Exception:
        pass
    return n

def run(seconds=None):
    store.init_db()
    t0 = time.time()
    total = 0
    # browser/recent beim start einmal von der letzten stunde ziehen
    _state["last_browser"] = 0
    _state["last_recent"] = 0
    while True:
        total += sweep()
        if seconds is not None and time.time() - t0 >= seconds:
            break
        time.sleep(config.WATCH_INTERVAL_SEC)
    return total

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--once" in args:
        store.init_db(); print("sweep events:", sweep())
    elif "--seconds" in args:
        sec = int(args[args.index("--seconds") + 1])
        n = run(seconds=sec); print(f"ran {sec}s, events added: {n}"); print("counts:", store.counts())
    else:
        print("watcher dauerloop... (Ctrl-C zum stoppen)")
        run()

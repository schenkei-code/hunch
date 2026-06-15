# -*- coding: utf-8 -*-
"""Runtime/Launcher — startet die ganze Machine mit EINEM befehl.
Dauer-loop: watcher-sweeps + periodisch baseline/graph-rebuild + periodisch brain (als subprozess,
non-blocking). Heartbeat in store.meta fuer health-check. Crasht nie: alles in try/except, auto-continue.
  python -m hunch.run            -> foreground dauerloop
  python -m hunch.run --once     -> ein zyklus (test)
  python -m hunch.run --install-task   -> Windows scheduled task (autostart at logon)
  python -m hunch.run --uninstall-task"""
import sys, time, os, subprocess, json
from . import config, store, watcher, baseline, graph, brain

PY = config.PY_BIN or sys.executable

def _heartbeat(kind):
    with store.cursor() as con:
        con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=?",
                    (f"hb_{kind}", str(time.time()), str(time.time())))

def health():
    out = {}
    with store.cursor() as con:
        for k in ("hb_watch", "hb_brain", "hb_baseline"):
            r = con.execute("SELECT value FROM meta WHERE key=?", (k,)).fetchone()
            out[k] = float(r["value"]) if r else None
    out["counts"] = store.counts()
    now = time.time()
    out["watcher_alive"] = bool(out.get("hb_watch") and now - out["hb_watch"] < 60)
    return out

def rebuild_profile():
    try:
        baseline.run(); graph.build_graph(rebuild=True); _heartbeat("baseline")
        return True
    except Exception as e:
        print("[rebuild err]", e); return False

def trigger_brain():
    """brain als eigener subprozess -> blockt den watcher nicht, kann ihn nicht crashen."""
    try:
        subprocess.Popen([PY, "-m", "hunch.brain"], cwd=str(config.ROOT),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _heartbeat("brain")
    except Exception as e:
        print("[brain trigger err]", e)

def _single_instance():
    """lockfile mit pid -> verhindert doppel-instanzen (autostart + manuell)."""
    lock = config.DATA_DIR / "runtime.pid"
    try:
        if lock.exists():
            old = int(lock.read_text().strip() or 0)
            try:
                import psutil
                if old and psutil.pid_exists(old):
                    print(f"[machine] laeuft schon (pid {old}) — exit"); return False
            except Exception:
                pass
        lock.write_text(str(os.getpid()))
        return True
    except Exception:
        return True

def loop(once=False):
    store.init_db()
    if not once and not _single_instance():
        return
    print(f"[machine] runtime start · py={PY}")
    if store.counts()["messages"] == 0:
        try:
            from . import ingest; ingest.run(); print("[machine] erstes ingest gelaufen")
        except Exception as e:
            print("[ingest err]", e)
    last_brain = 0.0
    last_baseline = 0.0
    while True:
        t = time.time()
        try:
            watcher.sweep(); _heartbeat("watch")
        except Exception as e:
            print("[watch err]", e)
        if t - last_baseline > config.BASELINE_EVERY_MIN * 60:
            rebuild_profile(); last_baseline = t
        if t - last_brain > config.BRAIN_EVERY_MIN * 60:
            trigger_brain(); last_brain = t
        if once:
            break
        time.sleep(config.WATCH_INTERVAL_SEC)

# ---------- Windows autostart (Startup-ordner, KEIN admin noetig) ----------
def _startup_dir():
    return os.path.join(os.path.expanduser("~"),
                        "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup")
_VBS = "hunch.vbs"

def install_task():
    """legt ein hidden-launcher-vbs in den Startup-ordner -> autostart bei jedem logon, ohne admin."""
    vbs = (f'Set s = CreateObject("WScript.Shell")\r\n'
           f's.CurrentDirectory = "{config.ROOT}"\r\n'
           f's.Run "cmd /c ""{PY}"" -m hunch.run", 0, False\r\n')
    p = os.path.join(_startup_dir(), _VBS)
    try:
        os.makedirs(_startup_dir(), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(vbs)
        print("autostart installiert ->", p)
        return True
    except Exception as e:
        print("install err", e); return False

def uninstall_task():
    p = os.path.join(_startup_dir(), _VBS)
    try:
        if os.path.exists(p):
            os.remove(p); print("autostart entfernt ->", p)
        else:
            print("kein autostart-eintrag da")
        return True
    except Exception as e:
        print("uninstall err", e); return False

if __name__ == "__main__":
    a = sys.argv[1:]
    if "--install-task" in a:
        install_task()
    elif "--uninstall-task" in a:
        uninstall_task()
    elif "--health" in a:
        print(json.dumps(health(), indent=1))
    elif "--once" in a:
        loop(once=True); print("health:", json.dumps(health()))
    else:
        loop()

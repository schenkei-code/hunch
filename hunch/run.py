# -*- coding: utf-8 -*-
"""Runtime/Launcher — startet die ganze Machine mit EINEM befehl.
Dauer-loop: watcher-sweeps + periodisch baseline/graph-rebuild + periodisch brain (als subprozess,
non-blocking). Heartbeat in store.meta fuer health-check. Crasht nie: alles in try/except, auto-continue.
  python -m hunch.run            -> foreground dauerloop
  python -m hunch.run --once     -> ein zyklus (test)
  python -m hunch.run --install-task   -> Windows scheduled task (autostart at logon)
  python -m hunch.run --uninstall-task"""
import sys, time, os, subprocess, json
from . import config, store, watcher, baseline, graph, brain, bridge, ingest, session_sync, share, inbox

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
        # bridge: Hunch's live-read ins externe memory exportieren (falls konfiguriert)
        try:
            ok, info = bridge.export()
            if ok:
                _heartbeat("bridge")
        except Exception as e:
            print("[bridge err]", e)
        # share: profil (md+json) in den gemeinsamen ordner publizieren -> alle agenten lesen es
        try:
            ok, info = share.publish()
            if ok:
                _heartbeat("share")
        except Exception as e:
            print("[share err]", e)
        return True
    except Exception as e:
        print("[rebuild err]", e); return False

def bootstrap(force=False):
    """EINMALIGER cold-start: zieht beim ersten install automatisch ALLES rein —
    infos/memories (ingest) + ALLE bisherigen sessions wort-fuer-wort (session_sync) —
    und faehrt dann den vollen hunch-modus hoch (baseline + graph + bridge).
    Idempotent via meta-flag; force=True erzwingt erneut. Nie blockierend."""
    store.init_db()
    done = store.get_profile("_bootstrapped")
    if done and not force:
        return {"skipped": "schon gebootstrappt"}
    rep = {}
    print("[hunch] bootstrap: ziehe alles einmal rein …")
    try:
        rep["ingest"] = ingest.run()
    except Exception as e:
        rep["ingest_err"] = str(e)[:120]
    try:
        rep["sessions"] = session_sync.run(only_new=False)
        print(f"[hunch] sessions: {rep['sessions']}")
    except Exception as e:
        rep["sessions_err"] = str(e)[:120]
    # beitraege anderer agenten (inbox) gleich mit einsammeln
    try:
        rep["inbox"] = inbox.ingest()
    except Exception as e:
        rep["inbox_err"] = str(e)[:120]
    rebuild_profile()
    store.set_profile("_bootstrapped", time.time())
    rep["counts"] = store.counts()
    print(f"[hunch] bootstrap fertig · {rep['counts']}")
    return rep

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

def _reader_loop(once=False):
    """READER-modus (multi-agent): schreibt NICHT ins gemeinsame profil + kein brain.
    Beobachtet nur lokal (eigene db) und liest das gemeinsame profil — so kann nie ein
    zweites brain den shared-store/db zerlegen. Andere agenten brauchen dafuer gar kein
    Hunch: sie lesen einfach share/hunch_profile.json + haengen an die inbox."""
    print("[hunch] reader-modus — nur lokal beobachten + lesen, kein shared-write/brain")
    while True:
        try:
            watcher.sweep(); _heartbeat("watch")
        except Exception as e:
            print("[watch err]", e)
        if once:
            break
        time.sleep(config.WATCH_INTERVAL_SEC)

def loop(once=False):
    store.init_db()
    if not once and not _single_instance():
        return
    role = share.resolve_role()
    print(f"[hunch] runtime start · py={PY} · role={role}")
    if role == "reader":
        _reader_loop(once); return
    # ----- BRAIN: der EINE schreiber. haelt das brain-lock, sammelt inbox, publiziert profil -----
    share.acquire_or_refresh_lock()
    # beim allerersten lauf (frische installation): automatisch alles einmal reinziehen
    if not store.get_profile("_bootstrapped"):
        try:
            bootstrap()
        except Exception as e:
            print("[bootstrap err]", e)
    last_brain = last_baseline = last_sync = last_inbox = 0.0
    while True:
        t = time.time()
        # falls ein ANDERES frisches brain auftaucht -> freiwillig zum reader wechseln (ein-brain-regel)
        if not share.acquire_or_refresh_lock():
            print("[hunch] anderes brain aktiv -> wechsel in reader-modus")
            _reader_loop(once); return
        try:
            watcher.sweep(); _heartbeat("watch")
        except Exception as e:
            print("[watch err]", e)
        # inbox-beitraege der anderen agenten haeufig + guenstig einsammeln
        if t - last_inbox > 60:
            try:
                inbox.ingest(); _heartbeat("inbox")
            except Exception as e:
                print("[inbox err]", e)
            last_inbox = t
        # neue sessions inkrementell nachziehen (nur veraenderte transcripts)
        if t - last_sync > config.BASELINE_EVERY_MIN * 60:
            try:
                session_sync.run(only_new=True); _heartbeat("session_sync")
            except Exception as e:
                print("[session_sync err]", e)
            last_sync = t
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
    elif "--bootstrap" in a:
        print(json.dumps(bootstrap(force=("--force" in a)), indent=1, ensure_ascii=False))
    elif "--sync" in a:
        print(json.dumps(session_sync.run(only_new=("--full" not in a)), indent=1, ensure_ascii=False))
    elif "--publish" in a:
        store.init_db(); ok, info = share.publish(); print("publish:", "OK ->" if ok else "FAIL:", info)
    elif "--ingest-inbox" in a:
        print(json.dumps(inbox.ingest(), indent=1, ensure_ascii=False))
    elif "--role" in a:
        print("role:", share.resolve_role(), "· lock:", json.dumps(share.read_lock()))
    elif "--once" in a:
        loop(once=True); print("health:", json.dumps(health()))
    else:
        loop()

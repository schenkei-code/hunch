# -*- coding: utf-8 -*-
"""CLI fuer die Machine — abfragbar machen. Wird vom /machine-slash-command aufgerufen.
  python -m hunch.cli status        -> health + letzter nudge + top-signale + profil
  python -m hunch.cli scan          -> aktuelle anomalie-/chancen-signale
  python -m hunch.cli why <name>    -> wie haengt <name> zusammen (graph)
  python -m hunch.cli profile       -> pattern-of-life
  python -m hunch.cli sync [--full] -> bisherige Claude-Code-sessions reinziehen
  python -m hunch.cli mood          -> stimmungs-verlauf (emotion-proxy ueber sessions)
  python -m hunch.cli nudge         -> jetzt einen nudge erzwingen (force)"""
import sys, time, datetime, json
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
from . import store, detect, graph, run as runtime

def _ago(ts):
    if not ts: return "nie"
    s = time.time() - ts
    if s < 90: return f"{int(s)}s her"
    if s < 5400: return f"{int(s/60)}min her"
    if s < 172800: return f"{int(s/3600)}h her"
    return f"{int(s/86400)}d her"

def status():
    h = runtime.health()
    c = h["counts"]
    print("🧠 HUNCH — status")
    print(f"  watcher: {'🟢 live' if h['watcher_alive'] else '🔴 aus'}  (letzter beat {_ago(h.get('hb_watch'))})")
    print(f"  daten: {c['events']} events · {c['messages']} messages · {c['entities']} entitaeten · {c['edges']} graph-kanten · {c['nudges']} nudges")
    with store.cursor() as con:
        r = con.execute("SELECT ts,text FROM nudges WHERE sent=1 ORDER BY ts DESC LIMIT 1").fetchone()
    print(f"  letzter nudge: {_ago(r['ts']) if r else 'noch keiner'}")
    if r: print(f"    „{r['text'][:120]}“")
    det = detect.run()
    print(f"  fokus grad: {', '.join(det['focus'][:6]) or '(noch wenig live-daten)'}")
    if det["signals"]:
        print("  top-signale:")
        for s in det["signals"][:3]:
            print(f"    [{s['type']}] {s['score']} · {s['text'][:90]}")

def scan():
    det = detect.run()
    print("🔎 aktuelle signale:")
    if not det["signals"]:
        print("  (keine — alles im normalbereich)")
    for s in det["signals"]:
        print(f"  [{s['type']:15}] {s['score']} · {s['text']}")

def why(name):
    print(f"🕸  '{name}' im wissensgraph:")
    nb = graph.neighbors(name, k=10)
    if not nb:
        print("  (nicht im graph / zu selten)")
        return
    for n, w in nb:
        print(f"  ── {n}  (staerke {w})")
    dc = graph.dot_connect([name], k=5)
    if dc:
        print("  bruecken (denk-an-X):", ", ".join(f"{d['entity']}" for d in dc))

def profile():
    s = store.get_profile("summary") or {}
    print("👤 pattern of life:")
    print("  peak-stunden:", s.get("peak_hours"))
    print("  top-apps:", s.get("top_apps"))
    print("  top-themen:", ", ".join(s.get("top_topics", [])[:12]))
    print("  top-entitaeten:", ", ".join(s.get("top_entities", [])[:12]))
    ah = store.get_profile("active_hours_real") or {}
    live = {h: n for h, n in ah.items() if n > 0}
    print("  aktiv-stunden (live):", live or "(watcher sammelt noch)")

def sync(full=False):
    from . import session_sync
    print(f"🔄 ziehe Claude-Code-sessions ({'KOMPLETT' if full else 'nur neue'}) …")
    r = session_sync.run(only_new=not full)
    print(f"  {r['files_scanned']} sessions gescannt · {r['files_with_new']} mit neuem · "
          f"{r['messages_inserted']} messages neu im store (von {r['messages_parsed']} geparsed)")

def mood():
    print("🎭 stimmungs-verlauf (emotion-proxy, nur deine getippten session-messages):")
    with store.cursor() as con:
        rows = con.execute(
            "SELECT meta FROM messages WHERE source='session' AND role='user' "
            "AND meta IS NOT NULL AND json_extract(meta,'$.auto') IS NULL").fetchall()
    if not rows:
        print("  (noch keine sessions gesynct — 'sync --full' laufen lassen)")
        return
    from collections import Counter
    labels, sig = Counter(), Counter()
    pol = []
    for r in rows:
        try:
            m = json.loads(r["meta"])
        except Exception:
            continue
        if m.get("emotion"):
            labels[m["emotion"]] += 1
        if isinstance(m.get("polarity"), (int, float)):
            pol.append(m["polarity"])
        for s in (m.get("emo_signals") or []):
            sig[s] += 1
    total = sum(labels.values()) or 1
    print(f"  {total} bewertete messages · ø-polaritaet {sum(pol)/len(pol):+.2f}" if pol else f"  {total} messages")
    for lab, n in labels.most_common():
        bar = "█" * max(1, int(30 * n / total))
        print(f"    {lab:12} {bar} {n} ({100*n//total}%)")
    if sig:
        print("  haeufigste signale:", ", ".join(f"{k}×{v}" for k, v in sig.most_common(6)))

def nudge():
    from . import brain
    print("⚡ erzwinge einen nudge...")
    print(json.dumps(brain.run(force=True), ensure_ascii=False, indent=1))

def main(argv):
    cmd = (argv[0] if argv else "status").lower()
    if cmd == "status": status()
    elif cmd == "scan": scan()
    elif cmd == "why" and len(argv) > 1: why(" ".join(argv[1:]))
    elif cmd == "profile": profile()
    elif cmd == "sync": sync(full=("--full" in argv))
    elif cmd == "mood": mood()
    elif cmd == "nudge": nudge()
    else:
        print("usage: status | scan | why <name> | profile | sync [--full] | mood | nudge")

if __name__ == "__main__":
    main(sys.argv[1:])

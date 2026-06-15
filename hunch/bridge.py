# -*- coding: utf-8 -*-
"""Bridge — exportiert Hunch's aktuelle erkenntnisse als markdown in ein externes memory.
Einweg (Hunch -> memory), damit z.B. eine Claude-Code-session Hunch's live-read ueber den user sieht.
Nur aktiv wenn config.MEMORY_EXPORT_PATH gesetzt ist (config.local.json) -> public repo bleibt clean."""
import time, datetime, collections
from . import config, store, detect, graph

def _peak_hours():
    real = store.get_profile("active_hours_real") or {}
    if sum(real.values()) >= 40:
        src, label = real, "live"
    else:
        src, label = (store.get_profile("active_hours_all") or {}), "aus archiv (live noch dünn)"
    top = sorted(src.items(), key=lambda x: -x[1])[:4]
    return [h for h, n in top if n > 0], label

def build_markdown():
    summ = store.get_profile("summary") or {}
    det = detect.run()
    peaks, plabel = _peak_hours()
    c = store.counts()
    ents = summ.get("top_entities", [])[:10]

    # graph-highlights: fuer die top-3 entitaeten je die staerkste verbindung
    highlights = []
    for e in ents[:5]:
        nb = graph.neighbors(e, k=1)
        if nb and nb[0][0]:
            highlights.append(f"{e} ↔ {nb[0][0]}")

    lines = []
    lines.append("---")
    lines.append("name: Hunch Live-Read")
    lines.append("description: Was Hunch (lokaler proaktiver watcher) GRAD über Dominik beobachtet — live pattern-of-life, aktueller fokus, signale. Auto-exportiert, point-in-time.")
    lines.append("metadata:")
    lines.append("  type: reference")
    lines.append("---")
    lines.append("")
    lines.append(f"_Auto-Export von Hunch · {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')} · {c['events']} events · {c['messages']} msgs · {c['entities']} entitäten_")
    lines.append("")
    lines.append(f"**Aktiv-Rhythmus ({plabel}):** Peak-Stunden {peaks}")
    lines.append(f"**Häufigste Apps:** {', '.join(summ.get('top_apps', [])[:5]) or '—'}")
    lines.append(f"**Top-Themen (Baseline):** {', '.join(summ.get('top_topics', [])[:10]) or '—'}")
    lines.append(f"**Wiederkehrende Entitäten:** {', '.join(ents) or '—'}")
    lines.append("")
    lines.append(f"**Woran er GERADE dran is (recent focus):** {', '.join(det.get('focus', [])[:8]) or '(wenig live-daten)'}")
    if highlights:
        lines.append(f"**Starke Verbindungen im Graph:** {' · '.join(highlights)}")
    lines.append("")
    if det.get("signals"):
        lines.append("**Aktuelle Signale/Auffälligkeiten:**")
        for s in det["signals"][:4]:
            lines.append(f"- [{s['type']}] {s['text']}")
    else:
        lines.append("**Aktuelle Signale:** keine — alles im Normalbereich.")
    lines.append("")
    lines.append("_Quelle: lokaler Hunch-Store (~/hunch). Point-in-time, kein Ersatz für dominik.md._")
    return "\n".join(lines) + "\n"

def export():
    if not config.MEMORY_EXPORT_PATH:
        return False, "kein export-pfad (memory_export_path in config.local.json setzen)"
    try:
        p = config.MEMORY_EXPORT_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(build_markdown(), encoding="utf-8")
        return True, str(p)
    except Exception as e:
        return False, str(e)[:120]

if __name__ == "__main__":
    ok, info = export()
    print("export:", "OK ->" if ok else "FAIL:", info)
    if not config.MEMORY_EXPORT_PATH:
        print("--- preview (kein pfad gesetzt) ---")
        print(build_markdown())

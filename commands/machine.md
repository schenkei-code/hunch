---
description: The Machine abfragen — status, scan, why <name>, profile, nudge
argument-hint: "[status|scan|why <name>|profile|nudge]"
---

Führe das Machine-CLI mit den Argumenten `$ARGUMENTS` aus (Default `status`, wenn leer) und zeig dem User das Ergebnis 1:1:

```
cd ~/the-machine && PYTHONIOENCODING=utf-8 python -m machine.cli $ARGUMENTS
```

Unterbefehle:
- `status` — läuft der Watcher? Datenstand, letzter Nudge, aktueller Fokus, Top-Signale
- `scan` — aktuelle Anomalie-/Chancen-Signale
- `why <name>` — wie hängt etwas im Wissensgraph zusammen (Nachbarn + Brücken)
- `profile` — Pattern of Life (Rhythmus, Apps, Themen, Entitäten)
- `nudge` — jetzt einen Impuls erzwingen (force, ignoriert Ruhezeiten/Gap)

Gib die CLI-Ausgabe direkt wieder, ohne sie umzuformulieren. Wenn der User keinen Unterbefehl nennt, nimm `status`.

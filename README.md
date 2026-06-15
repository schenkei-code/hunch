# 🧠 The Machine

A self-contained **proactive AI partner** that runs locally on your PC. Inspired by the "Machine" from *Person of Interest* — but honest about what's real vs sci-fi.

It quietly watches your activity, learns your patterns and how your topics connect, and — when your current focus lines up with something useful from your past — sends you a subtle, well-timed nudge that feels like your own thought.

No cloud. No external memory service. Everything stays in a local SQLite DB on your machine.

## What it actually does

```
WATCH ──▶ STORE ──▶ BASELINE ──▶ GRAPH ──▶ DETECT ──▶ GATE ──▶ BRAIN ──▶ nudge
```

1. **Watch** — active window/app, browser history, opened files, clipboard, active times. Logs only on change (no spam).
2. **Baseline** — builds a *pattern of life*: your rhythm, apps, recurring topics & entities.
3. **Graph** — a self-built knowledge graph (entities = nodes, co-occurrence = edges) so it knows what relates to what. Dot-connecting in < 1 s.
4. **Detect** — compares "what you're on right now" vs your baseline + graph → opportunities ("your focus connects to X"), spikes, dormant-project revival, unusual hours.
5. **Gate** — quality filter: score threshold + quiet hours + min gap between nudges. So it never spams you.
6. **Brain** — turns a worthwhile signal into a casual, subtle nudge (via `claude -p`) and sends it to your Telegram.

> The honest part: it does **not** predict problems weeks ahead from invisible micro-anomalies. It connects your *real* signals — which already feels surprisingly prescient.

## Setup

1. **Deps:** `pip install pywin32 psutil` (Windows). Needs the `claude` CLI on PATH for nudge phrasing.
2. **Config:** copy `config.example.json` → `config.local.json` and fill in:
   - `chat_id` — your Telegram chat id (or set env `MACHINE_CHAT_ID`)
   - `bot_token` — your Telegram bot token (or env `MACHINE_BOT_TOKEN`)
   - `user_desc` — a short description of you (shapes the nudge style)
   - `ingest_sources` — optional paths to your own notes/archives as cold-start material
   - `quiet_hours`, `nudge_min_score`, `nudge_min_gap_min` — tune to taste
3. **Run:**
   ```
   python -m machine.run            # foreground loop (watcher + scheduler)
   python -m machine.run --install-task    # autostart at logon (Startup folder, no admin)
   python -m machine.run --health   # is it alive?
   ```

## Query it

Either the CLI or the `/machine` slash command (Claude Code plugin):

```
/machine status        # is it live? what does it see right now?
/machine scan          # current signals
/machine why <name>    # how something connects in the graph
/machine profile       # your pattern of life
/machine nudge         # force a nudge now
```

## Privacy

Everything is **local**. The watcher captures a lot (that's the point) — it all lives in `data/machine.db` on your machine and is never uploaded. The only outbound traffic is the nudge to *your own* Telegram. `config.local.json`, the DB, and `.env` are gitignored and never leave your repo.

## Off switch

```
python -m machine.run --uninstall-task   # remove autostart
# then kill the process listed in data/runtime.pid
```

## Layout

```
machine/
  config.py     # config (env / config.local.json — no secrets in code)
  store.py      # SQLite store
  watcher.py    # PC signal collector
  ingest.py     # cold-start import of your archives
  baseline.py   # pattern-of-life profile
  graph.py      # knowledge graph + dot-connecting
  detect.py     # anomaly / opportunity detection
  brain.py      # nudge engine (claude -p) + Telegram
  cli.py        # status / scan / why / profile / nudge
  run.py        # runtime launcher + autostart + health
commands/machine.md   # /machine slash command
```

MIT.

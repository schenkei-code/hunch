# -*- coding: utf-8 -*-
"""Brain — der proaktive impulsgeber. Sammelt signale (detect), filtert via qualitaets-gate
(score + ruhezeiten + min-gap), formuliert via claude -p einen subtilen impuls im stil des users
und schickt ihn per telegram. Faellt nie aus: claude-fail -> template-fallback.
Brain NUDGED nur — keine eigenmaechtigen aktionen (laut briefing)."""
import sys, time, json, subprocess, datetime, urllib.request, urllib.parse
from . import config, store, detect, baseline, graph

# ---------- qualitaets-gate ----------
def gate(signals, force=False):
    if not signals:
        return None, "keine signale"
    top = signals[0]
    if force:
        return top, "force"
    h = datetime.datetime.now().hour
    q0, q1 = config.NUDGE_QUIET_HOURS
    if q0 <= h < q1:
        return None, f"ruhezeit ({h} uhr, still {q0}-{q1})"
    if top["score"] < config.NUDGE_MIN_SCORE:
        return None, f"score {top['score']} < gate {config.NUDGE_MIN_SCORE}"
    gap_min = (time.time() - store.last_nudge_ts()) / 60
    if gap_min < config.NUDGE_MIN_GAP_MIN:
        return None, f"erst {int(gap_min)}min seit letztem nudge (<{config.NUDGE_MIN_GAP_MIN})"
    return top, "passed"

# ---------- impuls formulieren (default: GRATIS lokale templates; optional LLM) ----------
def craft_nudge(signal, focus, profile_summary, timeout=90):
    # 1) GRATIS-default: lokale template-nudges (kein claude -p, kostet nix). Mehrere phrasings, variiert.
    d = signal.get("data", {}) or {}
    import hashlib
    def pick(opts):
        seed = hashlib.md5(json.dumps(d, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return opts[int(seed, 16) % len(opts)]
    templates = {
        "opportunity": [
            f"spannender gedanke: '{d.get('bridge','')}' hängt grad stark mit dem zusammen woran du dran bist — vielleicht steckt da ne idee/lösung drin 🤔",
            f"was wenn du das prinzip von '{d.get('bridge','')}' auf dein aktuelles thema überträgst? könnt passen.",
            f"'{d.get('bridge','')}' und dein jetziger fokus liegen näher beieinander als man denkt — evtl. die brücke?",
        ],
        "topic_spike": [
            f"'{d.get('term','')}' geht dir grad ordentlich durch den kopf… vielleicht lohnt's da kurz tiefer zu graben.",
            f"du bist grad voll auf '{d.get('term','')}' — heißer moment um das festzuhalten/zu vertiefen.",
        ],
        "dormant_revival": [
            f"'{d.get('entity','')}' taucht bei dir grad wieder auf — altes ding das nochmal dran is?",
            f"du gräbst grad '{d.get('entity','')}' wieder aus. da war doch mal was — vielleicht der richtige zeitpunkt.",
        ],
        "unusual_hours": [signal["text"]],
    }
    template = pick(templates.get(signal["type"], [signal["text"]]))

    # 2) OPTIONAL LLM-formulierung. Default engine = gemini (GRATIS free-tier). Fallback -> template.
    engine = (config.NUDGE_LLM or "off").lower()
    if engine in ("gemini", "claude"):
        ctx = {"signal": signal.get("text"), "signal_type": signal.get("type"), "data": d,
               "aktueller_fokus": focus[:5],
               "top_themen": (profile_summary or {}).get("top_topics", [])[:8]}
        prompt = (
            "Du bist 'Hunch' — ein stiller, proaktiver partner von " + config.USER_DESC + ". "
            "Du hast folgendes signal aus seiner aktivitaet erkannt:\n" + json.dumps(ctx, ensure_ascii=False)
            + "\n\nFormuliere EINEN kurzen impuls auf deutsch (max 2 saetze), der sich anfuehlt wie SEIN "
            "eigener gedanke / ein zufaelliger geistesblitz — NICHT wie ein alarm. locker, kleinschreibung, "
            "kein meta, kein 'als KI'. NUR der impuls-text, sonst nichts."
        )
        out = _run_llm(engine, prompt, timeout)
        if out and len(out) > 8:
            return out, engine
    return template, "template"

# CLI-noise (gemini startup-warnings etc.) der NICHT die antwort is
_NOISE_PREFIX = ("warning:", "ripgrep", "mcp issues", "skill ", "loaded cached", "data collection",
                 "[dotenv", "true color", "note:", "tip:", "deprecat")
def _run_llm(engine, prompt, timeout):
    try:
        if engine == "gemini":
            # gemini ist auf Windows ein npm .cmd-shim -> shell=True; prompt via stdin (kein arg-quoting),
            # -p "." triggert nur den headless-modus, der echte prompt kommt vom stdin.
            r = subprocess.run(f'"{config.GEMINI_BIN}" -m {config.GEMINI_MODEL} -p "."',
                               input=prompt, capture_output=True, text=True, timeout=timeout,
                               encoding="utf-8", shell=True)
        else:
            r = subprocess.run([config.CLAUDE_BIN, "-p", prompt, "--model", config.NUDGE_MODEL,
                                "--strict-mcp-config"], capture_output=True, text=True,
                               timeout=timeout, encoding="utf-8")
        out = (r.stdout or "").strip()
        if not out:
            return None
        # noise-zeilen rausfiltern, echte antwort behalten
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()
                 and not ln.strip().lower().startswith(_NOISE_PREFIX)]
        text = " ".join(lines).strip()
        return text[:600] if text else None
    except Exception:
        return None

# ---------- telegram ----------
def send_telegram(text):
    if not config.BOT_TOKEN:
        return False, "kein bot-token"
    try:
        data = urllib.parse.urlencode({"chat_id": config.CHAT_ID, "text": text}).encode()
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{config.BOT_TOKEN}/sendMessage", data=data)
        with urllib.request.urlopen(req, timeout=20) as resp:
            ok = json.loads(resp.read().decode()).get("ok", False)
            return ok, "sent" if ok else "api-fail"
    except Exception as e:
        return False, str(e)[:80]

# ---------- haupt-lauf ----------
def run(force=False, dry=False):
    store.init_db()
    det = detect.run()
    chosen, reason = gate(det["signals"], force=force)
    result = {"reason": reason, "n_signals": len(det["signals"]), "focus": det["focus"]}
    if not chosen:
        result["nudged"] = False
        return result
    summary = store.get_profile("summary") or {}
    text, via = craft_nudge(chosen, det["focus"], summary)
    result.update({"signal": chosen["type"], "score": chosen["score"], "via": via, "text": text})
    nid = store.add_nudge(text, chosen["type"], chosen["score"], sent=0,
                          meta={"via": via, "signal": chosen})
    if dry:
        result["nudged"] = False; result["dry"] = True
        return result
    ok, info = send_telegram(text)
    if ok:
        with store.cursor() as con:
            con.execute("UPDATE nudges SET sent=1 WHERE id=?", (nid,))
    result["nudged"] = ok; result["send_info"] = info
    return result

if __name__ == "__main__":
    a = sys.argv[1:]
    print(json.dumps(run(force=("--force" in a), dry=("--dry" in a)), indent=1, ensure_ascii=False))

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

# ---------- impuls formulieren (claude -p, mit fallback) ----------
def craft_nudge(signal, focus, profile_summary, timeout=90):
    ctx = {
        "signal": signal["text"], "signal_type": signal["type"], "data": signal.get("data"),
        "aktueller_fokus": focus[:5],
        "top_themen": (profile_summary or {}).get("top_topics", [])[:8],
    }
    prompt = (
        "Du bist 'The Machine' — ein stiller, proaktiver partner von " + config.USER_DESC + ". "
        "Du hast folgendes signal aus seiner aktivitaet erkannt:\n"
        + json.dumps(ctx, ensure_ascii=False)
        + "\n\nFormuliere EINEN einzigen, kurzen impuls auf deutsch (max 2 saetze), der sich anfuehlt "
        "wie SEIN eigener gedanke / ein zufaelliger geistesblitz — NICHT wie ein alarm oder 'ich hab "
        "erkannt dass...'. locker, kleinschreibung, kein meta, kein 'als KI', kein 'die machine'. "
        "stupse ihn nur sanft in richtung der verbindung/idee. nur der impuls-text, sonst nix."
    )
    try:
        r = subprocess.run(
            [config.CLAUDE_BIN, "-p", prompt, "--model", config.NUDGE_MODEL, "--strict-mcp-config"],
            capture_output=True, text=True, timeout=timeout, encoding="utf-8")
        out = (r.stdout or "").strip()
        if out and len(out) > 8:
            return out.split("\n\n")[0].strip()[:600], "claude"
    except Exception as e:
        pass
    # fallback: aus dem signal-text einen lockeren stupser bauen
    fb = {
        "opportunity": f"spannender gedanke: {signal['data'].get('bridge','')} koennte grad zu deinem thema passen — vielleicht steckt da ne idee drin 🤔",
        "topic_spike": f"dir scheint grad '{signal['data'].get('term','')}' im kopf rumzugehen… vielleicht lohnt's da kurz tiefer zu graben",
        "dormant_revival": f"{signal['data'].get('entity','')} taucht bei dir grad wieder auf — altes ding das nochmal dran is?",
        "unusual_hours": signal["text"],
    }.get(signal["type"], signal["text"])
    return fb, "fallback"

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

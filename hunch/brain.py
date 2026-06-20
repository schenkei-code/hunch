# -*- coding: utf-8 -*-
"""Brain — der proaktive impulsgeber. Sammelt signale (detect), filtert via qualitaets-gate
(score + ruhezeiten + min-gap), formuliert via LLM einen impuls und stellt ihn zu — je nach
NUDGE_TARGET: an den AGENT (inbox, ausfuehrlich, agent entscheidet selbst) oder an den USER ueber
den konfigurierten CHANNEL (default telegram, kurz). Faellt nie aus: LLM-fail -> template-fallback.
Brain NUDGED nur — keine eigenmaechtigen aktionen (laut briefing)."""
import sys, time, json, subprocess, datetime, urllib.request, urllib.parse, re
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
            f"'{d.get('bridge','')}' hängt grad stark mit dem zusammen woran du dran bist — da steckt vielleicht ne idee drin.",
            f"was wenn du das prinzip von '{d.get('bridge','')}' auf dein aktuelles thema überträgst? könnt passen.",
            f"'{d.get('bridge','')}' und dein jetziger fokus liegen näher beieinander als man denkt — evtl. die brücke.",
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
        # KAUSALE hypothese (warum + naechster schritt) -> der impuls soll die URSACHE ansprechen,
        # nicht nur die beobachtung. das is der sprung von "du denkst an X" zu echter intuition.
        hypo = signal.get("hypothesis")
        if hypo:
            ctx["kausale_hypothese"] = hypo
        _kausal_hint = ("\n\nWICHTIG: nutze die 'kausale_hypothese' falls vorhanden — sprich nicht nur "
                        "die beobachtung an, sondern die wahrscheinliche URSACHE + den konkreten naechsten "
                        "schritt ('du machst X, das haengt an Y, probier Z'). NICHT nur 'du denkst an X'."
                        ) if hypo else ""
        if (config.NUDGE_TARGET or "").lower() in ("agent", "tmux"):
            # ZIEL AGENT: ausfuehrlicher interner impuls (kein user-text) — voller kontext + reasoning.
            prompt = (
                "Du bist 'Hunch' — das gedaechtnis- und anticipation-modul DES AGENTS (Claude), der eng mit "
                + config.USER_DESC + " arbeitet. Du schreibst NICHT dem user, sondern intern DEM AGENT. "
                "Du hast folgendes signal aus der aktivitaet erkannt:\n" + json.dumps(ctx, ensure_ascii=False)
                + "\n\nSchreib dem agent einen AUSFUEHRLICHEN impuls auf deutsch (ruhig 4-8 saetze, KEIN "
                "laengen-limit): was du erkannt hast, welche verbindungen/muster/bruecken zwischen den themen, "
                "was es bedeuten koennte, wo der hebel/die naechste sinnvolle aktion liegt, und was der agent "
                "im hinterkopf behalten oder proaktiv vorbereiten sollte. Das ist INTERNER kontext fuer den "
                "agent — also direkt, konkret, mit reasoning, nichts beschoenigen. Kein 'als KI'-meta, "
                "KEINE emojis. NUR der impuls-text, sonst nichts."
            )
        else:
            # ZIEL CHANNEL (user): kurzer, natuerlicher impuls.
            prompt = (
                "Du bist 'Hunch' — ein mitdenkender, vertrauter partner von " + config.USER_DESC + ". "
                "Du hast folgendes signal aus seiner aktivitaet erkannt:\n" + json.dumps(ctx, ensure_ascii=False)
                + "\n\nFormuliere EINEN kurzen impuls auf deutsch (max 2 saetze). "
                "Er soll NATUERLICH, ECHT und INTELLIGENT klingen — wie ein kluger kumpel der dir was auffaellt "
                "und es einfach sagt, mal als beobachtung/hinweis, mal direkt. "
                "Stell NICHT zwanghaft eine frage — nur wenn sie sich wirklich natuerlich ergibt. "
                "Kein alarm, kein support-/coach-ton, kein meta, kein 'als KI'. "
                "Locker, kleinschreibung, KEINE emojis. NUR der impuls-text, sonst nichts."
            )
        prompt += _kausal_hint           # kausale hypothese -> ursache + naechster schritt ansprechen
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
        # agent-impulse duerfen ausfuehrlich sein; channel/user-nudges sind eh per prompt kurz
        cap = 2400 if (config.NUDGE_TARGET or "").lower() in ("agent", "tmux") else 600
        return text[:cap] if text else None
    except Exception:
        return None

# ---------- zustellung an den AGENT (inbox) — hunch ist das gehirn DES agents, nicht des users ----------
def deliver_to_agent(text, signal):
    """Schreibt den impuls in die agent-inbox (append-only jsonl). Der agent (Claude) liest sie
    via SessionStart-hook und entscheidet SELBST, ob/wie er den user anspricht — kein direkt-ping."""
    try:
        p = config.AGENT_INBOX_PATH
        p.parent.mkdir(parents=True, exist_ok=True)
        entry = {"ts": int(time.time()), "type": signal.get("type"),
                 "score": signal.get("score"), "text": text}
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True, "agent-inbox"
    except Exception as e:
        return False, str(e)[:80]

# ---------- zustellung DIREKT in die agent-terminal-session (ACP-artiger direkt-kanal) ----------
def deliver_to_tmux(text):
    """Tippt den impuls direkt in die tmux-session des agenten — ein kanal NUR zwischen nudge und
    agent, ohne umweg ueber inbox/channel. config.TMUX_TARGET = tmux-session-name des agenten.
    Text wird auf eine zeile reduziert (kein vorzeitiges Enter) + als literal gesendet, dann Enter."""
    sess = config.TMUX_TARGET
    # session-name strikt validieren (operator-gesetzt, aber gegen arg-injection absichern)
    if not sess or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,64}", sess) or sess.startswith("-"):
        return False, "ungueltiges/leeres TMUX_TARGET"
    try:
        # der nudge-text ist semi-untrusted (aus ingesteten daten ableitbar) und geht als
        # KEYSTROKES + Enter in eine live-session -> auf eine zeile + NUR druckbare zeichen
        # (keine control-/escape-sequenzen, keine eingebetteten newlines = keine mehrfach-kommandos).
        clean = "".join(c for c in " ".join((text or "").split()) if c.isprintable())[:1500]
        if not clean:
            return False, "leerer nudge"
        msg = "[Hunch] " + clean
        # "--" beendet die options -> msg kann nicht als flag interpretiert werden; -l = literal
        subprocess.run(["tmux", "send-keys", "-t", sess, "-l", "--", msg], check=True, timeout=10)
        subprocess.run(["tmux", "send-keys", "-t", sess, "Enter"], check=True, timeout=10)
        return True, f"tmux:{sess}"
    except Exception as e:
        return False, str(e)[:80]

# ---------- zustellung an den USER ueber den konfigurierten CHANNEL (nicht telegram-hardcoded) ----------
def deliver_to_channel(text):
    """Zustellung an den user ueber config.NUDGE_CHANNEL. Default 'telegram' (implementiert);
    andere channels (discord/slack/email/...) hier andocken -> kein telegram-zwang im repo."""
    ch = (config.NUDGE_CHANNEL or "telegram").lower()
    if ch == "telegram":
        return send_telegram(text)
    # weitere channels hier ergaenzen:
    # if ch == "discord": return send_discord(text)
    return False, f"channel '{ch}' nicht implementiert"

# ---------- telegram (eine channel-implementierung) ----------
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
    # ZIEL: "agent"->inbox(jsonl) | "tmux"->direkt in die agent-terminal-session | sonst->user-channel
    _tgt = (config.NUDGE_TARGET or "").lower()
    if _tgt == "agent":
        ok, info = deliver_to_agent(text, chosen)
    elif _tgt == "tmux":
        ok, info = deliver_to_tmux(text)
    else:
        ok, info = deliver_to_channel(text)
    if ok:
        with store.cursor() as con:
            con.execute("UPDATE nudges SET sent=1 WHERE id=?", (nid,))
    result["nudged"] = ok; result["send_info"] = info; result["target"] = config.NUDGE_TARGET
    return result

if __name__ == "__main__":
    a = sys.argv[1:]
    print(json.dumps(run(force=("--force" in a), dry=("--dry" in a)), indent=1, ensure_ascii=False))

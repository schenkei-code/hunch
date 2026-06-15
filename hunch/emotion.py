# -*- coding: utf-8 -*-
"""Emotion-Proxy — KEINE echte gefuehlserkennung (die gibt es nicht), sondern eine
ehrliche heuristik ueber den geschriebenen ton: GROSSSCHREIBUNG, ausrufezeichen,
flueche/abwinker (frust) vs. hype-woerter (begeisterung), kuerze+haerte (gereiztheit).
Sprachneutral angelegt, mit de+en lexika. Liefert label + polaritaet + erregung + signale.
Generisch & datenfrei — gehoert ins public repo."""
import re

# kleine, erweiterbare lexika (de + en). bewusst klein gehalten -> wenig false positives.
_NEG_WORDS = {
    # frust / abwinken / aerger
    "scheisse", "scheiße", "kacke", "mist", "nervt", "nervig", "egal", "vergiss", "vergess",
    "schwachsinn", "bloedsinn", "blödsinn", "unsinn", "kaputt", "dumm", "doof", "hass", "hasse",
    "nein", "ne", "nope", "stop", "stopp", "schlecht", "fehler", "falsch", "problem", "geht nicht",
    "funktioniert nicht", "fuck", "shit", "damn", "crap", "wtf", "ugh", "hate", "broken", "bug",
    "wrong", "stupid", "annoying", "useless", "terrible", "awful", "no",
}
_POS_WORDS = {
    # hype / lob / freude
    "geil", "mega", "perfekt", "stark", "super", "klasse", "hammer", "wahnsinn", "genial",
    "spitze", "nice", "cool", "top", "danke", "liebe", "lieb", "freu", "freue", "yes", "ja",
    "endlich", "richtig gut", "sehr gut", "passt", "perfect", "awesome", "amazing", "great",
    "love", "thanks", "thank", "nice", "sweet", "brilliant", "excellent", "wonderful", "happy",
}
_URGENT_WORDS = {
    "sofort", "schnell", "dringend", "jetzt", "asap", "now", "urgent", "quick", "immediately",
    "eilig", "wichtig", "important", "hurry",
}
_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+")


def _caps_ratio(text):
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 4:
        return 0.0
    up = sum(1 for c in letters if c.isupper())
    return up / len(letters)


def emotion(text, role="user"):
    """liefert {'label','polarity'(-1..1),'arousal'(0..1),'signals'[...]}.
    role nur informativ — assistant-text wird genauso bewertet (selten emotional)."""
    t = (text or "").strip()
    if not t:
        return {"label": "leer", "polarity": 0.0, "arousal": 0.0, "signals": []}
    low = t.lower()
    words = set(w for w in _WORD_RE.findall(low))
    signals = []

    neg = len(words & _NEG_WORDS)
    pos = len(words & _POS_WORDS)
    urg = len(words & _URGENT_WORDS)
    excl = t.count("!")
    ques = t.count("?")
    caps = _caps_ratio(t)
    n_words = max(1, len(_WORD_RE.findall(t)))
    terse = n_words <= 4

    if caps > 0.6 and n_words >= 2:
        signals.append("ALLCAPS")
    if excl >= 1:
        signals.append(f"{excl}x!")
    if ques >= 2:
        signals.append("fragend")
    if neg:
        signals.append("frust-woerter")
    if pos:
        signals.append("hype-woerter")
    if urg:
        signals.append("dringlich")
    if terse:
        signals.append("knapp")

    # arousal: wie aufgeladen (egal ob + oder -)
    arousal = min(1.0, 0.18 * excl + 0.6 * caps + 0.22 * (neg + pos + urg) + (0.1 if terse else 0))
    # polarity: positiv vs negativ
    raw = pos - neg
    polarity = max(-1.0, min(1.0, raw / 3.0))
    # GROSSSCHREIBUNG verstaerkt die vorhandene richtung (oder zieht richtung frust wenn neutral)
    if caps > 0.6:
        polarity = polarity - 0.25 if polarity <= 0 else polarity
        arousal = min(1.0, arousal + 0.15)

    # label ableiten
    if polarity <= -0.34 and arousal >= 0.45:
        label = "frustriert"
    elif polarity <= -0.2:
        label = "genervt"
    elif polarity >= 0.5 and arousal >= 0.4:
        label = "begeistert"
    elif polarity >= 0.25:
        label = "zufrieden"
    elif urg and arousal >= 0.4:
        label = "dringlich"
    elif arousal >= 0.55:
        label = "aufgeladen"
    else:
        label = "neutral"

    return {"label": label, "polarity": round(polarity, 2),
            "arousal": round(arousal, 2), "signals": signals}


if __name__ == "__main__":
    import sys
    for s in (sys.argv[1:] or ["Vergiss es", "Das ist ja RICHTIG GEIL!!!",
                                "kannst du das fixen?", "mach mal schnell jetzt sofort",
                                "ok"]):
        print(f"{s!r:45} -> {emotion(s)}")

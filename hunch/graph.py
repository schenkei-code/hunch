# -*- coding: utf-8 -*-
"""Mini-Wissensgraph + Dot-Connecting — eigenbau, kein graphify/obsidian.
Entitaeten = nodes, co-occurrence = edges. dot_connect() findet verbindungen zwischen
aktuellem fokus und alten nodes („das prinzip aus projekt X passt auf dein aktuelles Y")."""
import re, collections, heapq, math
from . import store, baseline, config
try:
    from . import embed as _embed
except Exception:
    _embed = None

# generische woerter die KEINE entitaet sind
NOISE = set(s.lower() for s in """
Users User Bild Video Problem Nachricht Ihre Nachrichten Foto Link Code Tool Plugin Datei Ordner
Hallo Danke Heute Morgen Abend Tag Woche Monat Jahr Stunde Minute Mail Email Account Status Update
Telegram Chat Channel Session Assistant System Prompt Test Beispiel Frage Antwort Info Dabei Damit
The This That What When Where Here There Just Like Make Done Next Step Run Build Okay
Bitte Ihnen Ihren Gerne Gruss Gruessen Gruesse Gruss Freundlichen Sehr Geehrte Geehrter Geehrten
Liebe Lieber Lieben Hallo Servus Wochenende Vormittag Nachmittag Mittag Mfg Lg Vielen Besten
Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag
Jetzt Lass Nicht Doch Klar Genau Sorry Passt Okay Gut Mach Schau Halt Eben Mal Bisschen
Dann Wenn Also Sobald Schon Noch Hier Dort Damit Dabei Sowas Etwas Irgendwas Alles Nichts
Google Chrome Edge Firefox Safari Browser Live Online Offline Desktop Mobile Window Tab Button Click
""".split() + ["grüße", "grüßen", "grüss", "für", "über"])

# entitaet = grossbuchstaben-start, multiword NUR ueber echte leerzeichen (NICHT ueber zeilenumbrueche
# -> sonst werden mail-signaturen wie "Gruessen\nMarkus" zu falschen entitaeten verklebt)
CAP = re.compile(r"\b([A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9]{2,}(?:[^\S\r\n][A-ZÄÖÜ][A-Za-zÄÖÜäöüß0-9]+){0,2})\b")
MAX_PER_DOC = 6   # max entitaeten pro message fuer edges

# fuehrende generische woerter -> multiword ist keine echte entitaet
_BADLEAD = set("ihre ihr ihrem ihrer ihres ihren guten die der das den dem ein eine aber dabei damit "
               "diese dieser dieses mein dein sein unser jede jeder jedes alle viele neue gute erste "
               "letzte vielen diesen diesem alle paar nur noch schon dann wenn also sobald falls weil "
               "sehr lieben liebe lieber besten freundlichen unsere unser unseren unserem unserer "
               "euer eure euren eurem meine meinen welche welcher welches".split())
_BADWORD = set("nachricht snapshot messages message dokument browser problem datei status update "
               "guten tag hallo danke ungelesen dank vielen erste letzte neue gesendet empfangen "
               "antwort frage info bild video foto link".split())

def extract_entities(text):
    out = []
    for m in CAP.findall(text or ""):
        ml = m.lower()
        if ml in NOISE or ml in config.USER_NAMES or len(m) < 4:
            continue
        toks = ml.split()
        if toks[0] in _BADLEAD:                  # 'Ihre Nachricht', 'Guten Tag'
            continue
        if all(t in _BADWORD or t in NOISE for t in toks):
            continue
        out.append(m)
    return out

# ---- entity-typ-inferenz (person / tool / topic) -> semantische struktur statt "alles topic" ----
_TECH = set("""
python javascript typescript java golang go rust ruby php swift kotlin react vue svelte angular node
nodejs deno bun docker kubernetes git github gitlab bitbucket sql nosql json yaml toml api rest graphql
html css scss tailwind ffmpeg sqlite postgres postgresql mysql mongodb redis nginx apache linux ubuntu
windows macos bash zsh powershell numpy pandas pytorch tensorflow sklearn claude chatgpt gpt gemini llm
npm pip cargo vite webpack esbuild rollup vercel netlify aws azure gcp supabase firebase stripe openai
anthropic huggingface ollama vllm whisper langchain figma photoshop blender unity unreal obsidian notion
""".split())
_PERSON_RE = re.compile(r"^[A-ZÄÖÜ][a-zäöüß]{2,}\s[A-ZÄÖÜ][a-zäöüß]{2,}$")   # 'Vorname Nachname'

def infer_kind(name):
    n = (name or "").strip()
    nl = n.lower()
    # tool/tech: bekannter tech-begriff, datei-endung, oder kurzes all-caps-akronym (API/JSON/SQL)
    if nl in _TECH or re.search(r"\.(py|js|ts|tsx|md|json|sh|sql|yml|yaml|toml|css|html)$", nl) \
            or (n.isupper() and 2 <= len(n) <= 5):
        return "tool"
    # person: 'Vorname Nachname' (zwei grossgeschriebene, beide rein-alphabetisch) — aber NICHT
    # wenn das erste wort ein generisches/fuehrungs-wort is ('Unsere Buerozeiten', 'Ihrem Anliegen')
    toks = nl.split()
    if _PERSON_RE.match(n) and toks and toks[0] not in _BADLEAD and toks[0] not in NOISE:
        return "person"
    return "topic"

def classify_entities():
    """setzt fuer alle entitaeten den typ (person/tool/topic) per heuristik. batch-update."""
    with store.cursor() as con:
        rows = con.execute("SELECT id, name FROM entities").fetchall()
        ups = [(infer_kind(r["name"]), r["id"]) for r in rows]
        con.executemany("UPDATE entities SET kind=? WHERE id=?", ups)
    return len(ups)

def build_graph(limit_docs=6000, rebuild=False):
    store.init_db()
    if rebuild:
        store.clear_edges("co")
    # 1) globale entity-frequenz bestimmen (fuer salienz)
    freq = collections.Counter()
    docs = []
    with store.cursor() as con:
        # code-dateien (role='code') NICHT in die entity-extraktion -> kein variablen-namen-rauschen
        rows = con.execute("SELECT text FROM messages WHERE role IS NULL OR role != 'code' LIMIT ?", (limit_docs,)).fetchall()
        rows += con.execute("SELECT title AS text FROM events WHERE title IS NOT NULL LIMIT 2000").fetchall()
    for r in rows:
        ents = extract_entities(r["text"])
        if ents:
            docs.append(ents)
            freq.update(ents)
    # nur entitaeten mit freq>=3 als nodes
    keep = {e for e, c in freq.items() if c >= 3}
    ids = store.upsert_entities_bulk(keep, kind="topic")
    # 2) co-occurrence edges (top-MAX_PER_DOC salienteste pro doc)
    edges = collections.Counter()
    for ents in docs:
        sal = sorted(set(e for e in ents if e in keep), key=lambda x: -freq[x])[:MAX_PER_DOC]
        for i in range(len(sal)):
            for j in range(i + 1, len(sal)):
                a, b = sorted((ids[sal[i]], ids[sal[j]]))
                edges[(a, b)] += 1
    store.add_edges_bulk(((a, b, w) for (a, b), w in edges.items()), kind="co")
    n_typed = classify_entities()   # person/tool/topic taggen -> semantische struktur
    n_emb = embed_entities(rebuild=rebuild)   # semantische vektoren (gemini-embedding-001 via OAuth)
    return {"nodes": len(keep), "edges": len(edges), "docs": len(docs), "typed": n_typed, "embedded": n_emb}


def embed_entities(rebuild=False, batch=400):
    """embedded entity-namen semantisch (gemini-embedding-001 via OAuth). inkrementell:
    nur entitaeten ohne vektor. faellt still aus wenn embed nich verfuegbar/kein OAuth."""
    if _embed is None or not getattr(config, "SEMANTIC_ON", True):
        return 0
    with store.cursor() as con:
        # NUR echte graph-knoten embedden (die mit kanten) — nich die 20k+ seltenen rausch-entitaeten
        rows = con.execute(
            "SELECT id, name FROM entities WHERE id IN "
            "(SELECT src FROM edges UNION SELECT dst FROM edges)").fetchall()
    have = set() if rebuild else store.entity_vec_ids()
    todo = [(r["id"], r["name"]) for r in rows if r["id"] not in have]
    if not todo:
        return 0
    done = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i+batch]
        vecs = _embed.embed([n for _, n in chunk])
        if not vecs or len(vecs) != len(chunk):
            break  # OAuth/embed-fail -> graph laeuft auf co-occurrence weiter
        store.set_entity_vecs_bulk((eid, v) for (eid, _), v in zip(chunk, vecs))
        done += len(chunk)
    return done


def semantic_neighbors(focus_names, k=6, min_sim=0.0):
    """semantische bruecken: entitaeten die dem fokus inhaltlich aehneln (auch OHNE co-occurrence).
    ergaenzt dot_connect. nutzt gespeicherte entity-vektoren. [] wenn keine vektoren da."""
    if _embed is None:
        return []
    vecs = store.get_entity_vecs()
    if not vecs:
        return []
    focus_ids = set(filter(None, (_eid(n) for n in focus_names)))
    fv = [vecs[i] for i in focus_ids if i in vecs]
    if not fv:
        return []
    # zentroid des fokus
    dim = len(fv[0]); cen = [sum(v[d] for v in fv)/len(fv) for d in range(dim)]
    n = math.sqrt(sum(x*x for x in cen)) or 1.0; cen = [x/n for x in cen]
    # fokus-namen-tokens fuer dubletten-filter (sonst kommen nur string-varianten:
    # "React"->"ReactJS","ReactRouter"). echte BRUECKEN = andere-aber-verwandte themen.
    foc_norms = [(_name(i) or "").strip().lower() for i in focus_ids]
    foc_tokens = set(t for fn in foc_norms for t in re.findall(r"\w+", fn) if len(t) > 2)

    def _is_variant(name):
        nm = (name or "").strip().lower()
        for fn in foc_norms:
            if fn and (fn in nm or nm in fn):   # substring-variante
                return True
        toks = set(re.findall(r"\w+", nm))
        return bool(toks & foc_tokens)          # teilt ein bedeutungs-token mit dem fokus

    scored = []
    for eid, v in vecs.items():
        if eid in focus_ids:
            continue
        s = sum(a*b for a, b in zip(cen, v))
        if s >= min_sim and s < 0.985:          # 0.985+ = quasi-identisch -> raus
            scored.append((s, eid))
    scored.sort(reverse=True)
    out = []
    with store.cursor() as con:
        for s, eid in scored:
            row = con.execute("SELECT name, kind FROM entities WHERE id=?", (eid,)).fetchone()
            if row and not _is_variant(row["name"]):
                out.append({"entity": row["name"], "kind": row["kind"], "sim": round(float(s), 3)})
                if len(out) >= k:
                    break
    return out

def _eid(name):
    norm = name.strip().lower()
    with store.cursor() as con:
        r = con.execute("SELECT id FROM entities WHERE norm=?", (norm,)).fetchone()
        return r["id"] if r else None

def _name(eid):
    with store.cursor() as con:
        r = con.execute("SELECT name FROM entities WHERE id=?", (eid,)).fetchone()
        return r["name"] if r else None

def kind_of(name):
    """typ einer entitaet (person/tool/topic) — fuer kausale hypothesen ('person X kann helfen')."""
    with store.cursor() as con:
        r = con.execute("SELECT kind FROM entities WHERE norm=?", ((name or "").strip().lower(),)).fetchone()
        return r["kind"] if r else "topic"

def neighbors(name, k=8):
    eid = _eid(name)
    if not eid:
        return []
    with store.cursor() as con:
        rows = con.execute(
            "SELECT CASE WHEN src=? THEN dst ELSE src END nb, weight FROM edges "
            "WHERE (src=? OR dst=?) AND kind IN ('co','seed') ORDER BY weight DESC LIMIT ?",
            (eid, eid, eid, k)).fetchall()
    return [(_name(r["nb"]), r["weight"]) for r in rows]

def dot_connect(focus_names, k=6):
    """fuer aktuellen fokus: ranke verbundene NICHT-fokus-entitaeten = die 'denk-mal-an-X'-bruecken."""
    focus_ids = set(filter(None, (_eid(n) for n in focus_names)))
    if not focus_ids:
        return []
    score = collections.Counter()
    with store.cursor() as con:
        for fid in focus_ids:
            for r in con.execute(
                "SELECT CASE WHEN src=? THEN dst ELSE src END nb, weight FROM edges "
                "WHERE (src=? OR dst=?) AND kind IN ('co','seed')", (fid, fid, fid)):
                if r["nb"] not in focus_ids:
                    score[r["nb"]] += r["weight"]
    out = []
    seen = set()
    with store.cursor() as con:
        for nb, w in score.most_common(k):
            row = con.execute("SELECT name, kind FROM entities WHERE id=?", (nb,)).fetchone()
            if row:
                out.append({"entity": row["name"], "kind": row["kind"], "strength": round(w, 1)})
                seen.add(row["name"])
    # semantische bruecken dazu (bedeutung statt exaktem co-occurrence) — fuellt auf bis k
    for sb in semantic_neighbors(focus_names, k=k):
        if sb["entity"] not in seen:
            sb["strength"] = round(sb.pop("sim") * 10, 1)  # sim 0..1 -> vergleichbare skala
            sb["via"] = "semantik"
            out.append(sb); seen.add(sb["entity"])
    out.sort(key=lambda x: -x["strength"])
    return out[:max(k, 6)]

def connect_path(a, b, max_hops=4):
    """kuerzeste verbindung zwischen zwei entitaeten (BFS) — 'wie haengt A mit B zusammen'."""
    sa, sb = _eid(a), _eid(b)
    if not sa or not sb:
        return None
    seen = {sa}
    q = [(sa, [sa])]
    while q:
        node, path = q.pop(0)
        if len(path) > max_hops:
            continue
        with store.cursor() as con:
            nbs = con.execute("SELECT CASE WHEN src=? THEN dst ELSE src END nb FROM edges WHERE src=? OR dst=?",
                              (node, node, node)).fetchall()
        for r in nbs:
            nb = r["nb"]
            if nb == sb:
                return [_name(x) for x in path + [nb]]
            if nb not in seen:
                seen.add(nb); q.append((nb, path + [nb]))
    return None

if __name__ == "__main__":
    import json, sys
    print("build:", json.dumps(build_graph()))
    # demo dot-connect auf dem ersten top-entity (falls vorhanden)
    s = store.get_profile("summary") or {}
    focus = (s.get("top_entities") or [])[:1]
    print("focus:", focus or "(noch keine entitaeten)")
    if focus:
        print("dot_connect:", json.dumps(dot_connect(focus), ensure_ascii=False))
        print("neighbors:", json.dumps(neighbors(focus[0]), ensure_ascii=False))

# -*- coding: utf-8 -*-
"""Semantische embeddings via Gemini Embedding (gemini-embedding-001) ueber Google-OAuth/Vertex (ADC).
KEIN API-key, kein billing. Wird vom graph genutzt um semantische bruecken zu finden (bedeutung statt exaktem wort).
Setze GCP_PROJECT/GCP_LOCATION (config.local.json oder env HUNCH_GCP_PROJECT / GOOGLE_CLOUD_PROJECT) +
`gcloud auth application-default login` einmalig. Faellt nie hart aus: bei fehler -> [] zurueck, graph laeuft dann nur auf co-occurrence weiter."""
import math, time
from . import config

_MODEL = getattr(config, "EMBED_MODEL", "gemini-embedding-001")
_PROJECT = getattr(config, "GCP_PROJECT", None) or None  # leer -> faellt auf GOOGLE_CLOUD_PROJECT env zurueck
_LOCATION = getattr(config, "GCP_LOCATION", "us-central1")
_DIM = int(getattr(config, "EMBED_DIM", 768))   # Matryoshka: 768 reicht, klein+schnell
_client = None

def _get_client():
    global _client
    if _client is None:
        from google import genai
        # project=None -> genai nutzt GOOGLE_CLOUD_PROJECT env / ADC-default-projekt
        _client = genai.Client(vertexai=True, project=_PROJECT or None, location=_LOCATION)
    return _client

def _normalize(v):
    n = math.sqrt(sum(x*x for x in v)) or 1.0
    return [x/n for x in v]

def embed(texts, task="SEMANTIC_SIMILARITY"):
    """liste von texten -> liste von (normalisierten) vektoren. [] bei fehler."""
    if not texts:
        return []
    try:
        from google.genai.types import EmbedContentConfig
        c = _get_client()
        out = []
        # batchen (API-limit ~250 inputs/call), retry-light
        for i in range(0, len(texts), 100):
            chunk = [(t or "")[:2000] for t in texts[i:i+100]]
            for attempt in range(3):
                try:
                    r = c.models.embed_content(
                        model=_MODEL, contents=chunk,
                        config=EmbedContentConfig(task_type=task, output_dimensionality=_DIM))
                    out.extend(_normalize(e.values) for e in r.embeddings)
                    break
                except Exception:
                    if attempt == 2: raise
                    time.sleep(1.5*(attempt+1))
        return out
    except Exception as e:
        print(f"[embed] fail: {str(e)[:120]}", flush=True)
        return []

def embed_one(text, task="SEMANTIC_SIMILARITY"):
    v = embed([text], task=task)
    return v[0] if v else None

def cosine(a, b):
    """a,b normalisiert -> dot = cosine."""
    return sum(x*y for x, y in zip(a, b))

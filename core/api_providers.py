"""Adapters Gemini + OpenAI pour le tri par IA cloud (port de providers.ts Android).

Contrat : recoit liste d'images locales, envoie a Gemini ou OpenAI, recupere
des clusters {nom propose, items}.

Strategie :
  - Resize chaque image en 1024px max + JPEG quality 70 via Pillow
  - Encode en base64
  - Envoie BATCH_SIZE images par requete avec prompt JSON
  - Merge clusters dont le nom normalise est equivalent
  - Cancellable via threading.Event

Aucune dependance externe : urllib (stdlib) + Pillow (deja installe).
"""

from __future__ import annotations
import base64
import io
import json
import re
import ssl
import threading
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Optional

import certifi
from PIL import Image


BATCH_SIZE = 20

ProviderId = Literal["gemini", "gemini-paid", "openai"]


@dataclass
class ApiClusterItem:
    path: Path


@dataclass
class ApiCluster:
    items: list[ApiClusterItem] = field(default_factory=list)
    suggested_name: str = ""


# Callback (current_batch, total_batches, label)
ProgressCb = Callable[[int, int, str], None]


# Sentinel par defaut
def _never_cancel() -> bool:
    return False


CancelCheck = Callable[[], bool]


class ApiCancelled(Exception):
    pass


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
PROMPT_FR = """Tu reçois plusieurs photos. Regroupe-les par thème ou sujet similaire (plage, repas, capture d'écran de cours, animal de compagnie, événement, document, etc.).

Règles :
- Une photo appartient à un seul groupe.
- Donne à chaque groupe un nom court et descriptif en français (3 mots max, sans guillemets).
- Une photo isolée (sans similaire) peut former son propre groupe.
- N'invente pas de noms vagues comme "Divers" ou "Autres", essaie d'être spécifique au contenu.

Réponds STRICTEMENT en JSON, rien d'autre, format :
{"groups":[{"name":"...","indices":[0,2,5]},{"name":"...","indices":[1,3]}]}

Les indices correspondent à l'ordre des photos reçues (0-indexé)."""


# ---------------------------------------------------------------------------
# Resize + encode JPEG b64
# ---------------------------------------------------------------------------
def prep_image_b64(path: Path, max_dim: int = 1024, quality: int = 70) -> Optional[str]:
    """Resize image en max_dim (cote le plus grand), JPEG quality, encode base64."""
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=quality, optimize=True)
            return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# HTTP helper avec timeout + cancellation
# ---------------------------------------------------------------------------
def _ssl_context() -> ssl.SSLContext:
    """Context SSL avec certifi (pour eviter les soucis de cert chain Windows)."""
    return ssl.create_default_context(cafile=certifi.where())


def _post_json(
    url: str,
    body: dict,
    headers: dict[str, str],
    timeout_s: float = 90.0,
    cancel_check: CancelCheck = _never_cancel,
) -> dict:
    """POST JSON avec timeout + check cancel apres reception."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)

    # Pas de moyen propre de canceller un urlopen au milieu. On verifie avant
    # et apres, et on fait confiance au timeout pour les coupures reseau.
    if cancel_check():
        raise ApiCancelled()

    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=_ssl_context()) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {e.code} : {body_txt}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error : {e}")

    if cancel_check():
        raise ApiCancelled()
    return json.loads(raw.decode("utf-8"))


# ---------------------------------------------------------------------------
# Extract JSON from LLM response
# ---------------------------------------------------------------------------
def _extract_groups(text: str) -> Optional[list[dict]]:
    """LLMs peuvent encadrer le JSON de ``` ou de baratin. On extrait."""
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(cleaned[start:end + 1])
        groups = parsed.get("groups")
        if not isinstance(groups, list):
            return None
        return groups
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Gemini (Google AI Studio)
# ---------------------------------------------------------------------------
GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)


def _call_gemini(api_key: str, images_b64: list[str], cancel_check: CancelCheck) -> list[dict]:
    parts: list[dict] = [{"text": PROMPT_FR}]
    for b64 in images_b64:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"response_mime_type": "application/json", "temperature": 0.2},
    }
    data = _post_json(
        GEMINI_URL, body,
        headers={"X-goog-api-key": api_key},
        cancel_check=cancel_check,
    )
    text = (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    groups = _extract_groups(text)
    if groups is None:
        raise RuntimeError("Gemini : reponse JSON invalide")
    return groups


# ---------------------------------------------------------------------------
# OpenAI (GPT-5 nano via Chat Completions)
# ---------------------------------------------------------------------------
OPENAI_MODEL = "gpt-5-nano"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"


def _call_openai(api_key: str, images_b64: list[str], cancel_check: CancelCheck) -> list[dict]:
    content: list[dict] = [{"type": "text", "text": PROMPT_FR}]
    for b64 in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"},
        })
    body = {
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": content}],
        "response_format": {"type": "json_object"},
        "max_completion_tokens": 4096,
    }
    data = _post_json(
        OPENAI_URL, body,
        headers={"Authorization": f"Bearer {api_key}"},
        cancel_check=cancel_check,
    )
    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    groups = _extract_groups(text)
    if groups is None:
        raise RuntimeError("OpenAI : reponse JSON invalide")
    return groups


# ---------------------------------------------------------------------------
# Pipeline principal
# ---------------------------------------------------------------------------
def _normalize_name(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().strip()


def analyze_with_api(
    provider: ProviderId,
    api_key: str,
    items: list[ApiClusterItem],
    on_progress: ProgressCb = lambda *_: None,
    cancel_check: CancelCheck = _never_cancel,
) -> list[ApiCluster]:
    """Analyse les items via l'API, retourne clusters mergees triees par taille."""
    total_batches = (len(items) + BATCH_SIZE - 1) // BATCH_SIZE
    merged: dict[str, ApiCluster] = {}

    for b in range(total_batches):
        if cancel_check():
            raise ApiCancelled()

        start = b * BATCH_SIZE
        batch = items[start:start + BATCH_SIZE]
        on_progress(b, total_batches, f"Preparation lot {b + 1}/{total_batches}...")

        # Prepare images en parallele leger (max 3 a la fois pour limiter RAM)
        b64s: list[Optional[str]] = []
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(prep_image_b64, it.path) for it in batch]
            for f in futures:
                if cancel_check():
                    raise ApiCancelled()
                b64s.append(f.result())

        valid_idx: list[int] = []
        valid_b64: list[str] = []
        for i, b64 in enumerate(b64s):
            if b64:
                valid_idx.append(i)
                valid_b64.append(b64)
        if not valid_b64:
            continue

        on_progress(b, total_batches, f"Envoi lot {b + 1}/{total_batches} ({len(valid_b64)} photos)...")

        if provider == "openai":
            groups = _call_openai(api_key, valid_b64, cancel_check)
        else:
            # 'gemini' et 'gemini-paid' utilisent le meme endpoint, distinction declarative
            groups = _call_gemini(api_key, valid_b64, cancel_check)

        for g in groups:
            name = g.get("name", "")
            indices = g.get("indices", [])
            if not isinstance(name, str) or not isinstance(indices, list):
                continue
            norm = _normalize_name(name)
            if not norm:
                continue
            group_items: list[ApiClusterItem] = []
            for llm_idx in indices:
                if not isinstance(llm_idx, int):
                    continue
                if llm_idx < 0 or llm_idx >= len(valid_idx):
                    continue
                batch_idx = valid_idx[llm_idx]
                group_items.append(batch[batch_idx])
            if not group_items:
                continue
            existing = merged.get(norm)
            if existing:
                existing.items.extend(group_items)
            else:
                merged[norm] = ApiCluster(items=group_items, suggested_name=name.strip())

    on_progress(total_batches, total_batches, f"Termine : {len(merged)} groupes.")
    return sorted(merged.values(), key=lambda c: -len(c.items))

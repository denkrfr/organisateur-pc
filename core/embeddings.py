"""Embeddings semantiques locaux via ONNX Runtime.

Deux modeles charges en lazy singletons :
  - CLIP-ViT-B/32 INT8 : encode images + texte en 512-d (meme espace)
  - multilingual-e5-small INT8 : encode texte multilingue en 384-d

Tout tourne en local sur CPU, 0 appel reseau.
Les vecteurs renvoyes sont L2-normalises, donc la similarite cosinus = dot product.

Cache disque des embeddings dans ~/.organisateur-pc/embeddings/<sha>.npy
indexe par (path + mtime + size) pour eviter de recalculer.
"""

from __future__ import annotations
import hashlib
import os
import sys
import threading
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image
import onnxruntime as ort
from tokenizers import Tokenizer


# ---------------------------------------------------------------------------
# Resource path (dev + PyInstaller bundle)
# ---------------------------------------------------------------------------
def _resource_path(*parts: str) -> Path:
    """Localise les fichiers de modeles : dev OU PyInstaller --add-data."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / Path(*parts)
    return Path(__file__).resolve().parent.parent / Path(*parts)


def _cache_dir() -> Path:
    d = Path.home() / ".organisateur-pc" / "embeddings"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fingerprint(path: Path) -> str:
    """ID stable d'un fichier : path + mtime + size (pour cache disque)."""
    try:
        st = path.stat()
        key = f"{path.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    except OSError:
        key = str(path)
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _load_cached(prefix: str, fp: str) -> Optional[np.ndarray]:
    p = _cache_dir() / f"{prefix}_{fp}.npy"
    if p.exists():
        try:
            return np.load(str(p))
        except Exception:  # noqa: BLE001
            return None
    return None


def _save_cached(prefix: str, fp: str, vec: np.ndarray) -> None:
    p = _cache_dir() / f"{prefix}_{fp}.npy"
    try:
        np.save(str(p), vec)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# CLIP : images + texte court (jusqu'a 77 tokens)
# ---------------------------------------------------------------------------
_CLIP_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_CLIP_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


class ClipEmbedder:
    _instance: Optional["ClipEmbedder"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        base = _resource_path("assets", "models", "clip")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
        opts.log_severity_level = 3  # WARN+
        self.vision = ort.InferenceSession(
            str(base / "vision_model.onnx"),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self.text = ort.InferenceSession(
            str(base / "text_model.onnx"),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = Tokenizer.from_file(str(base / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=77)
        self._text_cache: dict[str, np.ndarray] = {}
        self._cache_lock = threading.Lock()

    @classmethod
    def get(cls) -> "ClipEmbedder":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @staticmethod
    def is_available() -> bool:
        base = _resource_path("assets", "models", "clip")
        return (base / "vision_model.onnx").is_file()

    # ------------------------------------------------------------------
    def _preprocess_image(self, path: Path) -> np.ndarray:
        """Resize shortest=224, center crop, normalize, CHW, batch=1."""
        with Image.open(path) as img:
            img = img.convert("RGB")
            w, h = img.size
            if w < h:
                new_w = 224
                new_h = int(round(h * 224 / w))
            else:
                new_h = 224
                new_w = int(round(w * 224 / h))
            img = img.resize((new_w, new_h), Image.Resampling.BICUBIC)
            left = (new_w - 224) // 2
            top = (new_h - 224) // 2
            img = img.crop((left, top, left + 224, top + 224))
            arr = np.asarray(img, dtype=np.float32) / 255.0
        arr = (arr - _CLIP_MEAN) / _CLIP_STD
        arr = arr.transpose(2, 0, 1)[None, ...].astype(np.float32)
        return arr

    def encode_image(self, path: Path, use_cache: bool = True) -> Optional[np.ndarray]:
        fp = _fingerprint(path) if use_cache else ""
        if use_cache:
            cached = _load_cached("clip_img", fp)
            if cached is not None:
                return cached
        try:
            pixel_values = self._preprocess_image(path)
        except Exception:  # noqa: BLE001 — image corrompue, format non supporte
            return None
        try:
            out = self.vision.run(None, {"pixel_values": pixel_values})[0]
        except Exception:  # noqa: BLE001
            return None
        vec = out[0].astype(np.float32)
        n = np.linalg.norm(vec)
        if n > 1e-9:
            vec = vec / n
        if use_cache:
            _save_cached("clip_img", fp, vec)
        return vec

    def encode_text(self, text: str) -> Optional[np.ndarray]:
        if not text or not text.strip():
            return None
        text = text.strip()
        with self._cache_lock:
            cached = self._text_cache.get(text)
        if cached is not None:
            return cached
        enc = self.tokenizer.encode(text)
        ids = np.array([enc.ids], dtype=np.int64)
        try:
            out = self.text.run(None, {"input_ids": ids})[0]
        except Exception:  # noqa: BLE001
            return None
        vec = out[0].astype(np.float32)
        n = np.linalg.norm(vec)
        if n > 1e-9:
            vec = vec / n
        with self._cache_lock:
            if len(self._text_cache) < 2048:
                self._text_cache[text] = vec
        return vec


# ---------------------------------------------------------------------------
# E5 : texte multilingue (FR+EN+++) jusqu'a 512 tokens
# ---------------------------------------------------------------------------
class E5Embedder:
    """multilingual-e5-small. Comprend que 'facture'='invoice'='bill'.

    Convention E5 : on prefixe avec 'passage: ' pour les docs indexes et
    'query: ' pour les requetes. On utilise 'passage:' partout pour la
    symetrie (noms de dossier et contenus sont tous des passages).
    """

    _instance: Optional["E5Embedder"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        base = _resource_path("assets", "models", "e5")
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, (os.cpu_count() or 4) // 2)
        opts.log_severity_level = 3
        self.session = ort.InferenceSession(
            str(base / "model.onnx"),
            sess_options=opts,
            providers=["CPUExecutionProvider"],
        )
        self.tokenizer = Tokenizer.from_file(str(base / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self._cache: dict[str, np.ndarray] = {}
        self._cache_lock = threading.Lock()

    @classmethod
    def get(cls) -> "E5Embedder":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @staticmethod
    def is_available() -> bool:
        base = _resource_path("assets", "models", "e5")
        return (base / "model.onnx").is_file()

    def encode(self, text: str, prefix: str = "passage") -> Optional[np.ndarray]:
        if not text or not text.strip():
            return None
        full = f"{prefix}: {text.strip()[:2000]}"
        with self._cache_lock:
            cached = self._cache.get(full)
        if cached is not None:
            return cached
        enc = self.tokenizer.encode(full)
        ids = np.array([enc.ids], dtype=np.int64)
        mask = np.array([enc.attention_mask], dtype=np.int64)
        ttype = np.array([enc.type_ids], dtype=np.int64)
        try:
            out = self.session.run(None, {
                "input_ids": ids,
                "attention_mask": mask,
                "token_type_ids": ttype,
            })[0]
        except Exception:  # noqa: BLE001
            return None
        # Mean pooling avec masque
        mask_f = mask[0][..., None].astype(np.float32)
        summed = (out[0] * mask_f).sum(axis=0)
        counts = np.clip(mask_f.sum(axis=0), 1e-9, None)
        vec = (summed / counts).astype(np.float32)
        n = np.linalg.norm(vec)
        if n > 1e-9:
            vec = vec / n
        with self._cache_lock:
            if len(self._cache) < 2048:
                self._cache[full] = vec
        return vec


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Similarite cosinus. Les vecteurs sont L2-normalises -> dot product."""
    return float(np.dot(a, b))


def embeddings_available() -> bool:
    """True si les 2 modeles ont ete bundles correctement."""
    return ClipEmbedder.is_available() and E5Embedder.is_available()

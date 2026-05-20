"""Extraction de thumbnails video via ffmpeg bundle (imageio-ffmpeg).

Strategie :
  1. Cache disque sur ~/.organisateur-pc/video_thumbs/<hash>.jpg
  2. Si pas en cache : appel ffmpeg pour extraire la frame a 1s, scale a 256px
  3. Si extraction echoue (fichier corrompu, codec inconnu) : retourne None
     -> l'UI affichera son badge 'VIDEO' habituel comme fallback

Tout est dans un try/except : aucune chance que ca casse l'app, le pire qui
peut arriver c'est qu'on retourne None et qu'on retombe sur le badge.
"""

from __future__ import annotations
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional


CACHE_DIR = Path.home() / ".organisateur-pc" / "video_thumbs"

# Charge l'executable ffmpeg une seule fois. Si imageio-ffmpeg n'est pas
# disponible, on retombe gracieusement sur ffmpeg du systeme s'il existe.
_FFMPEG_PATH: Optional[str] = None
_FFMPEG_LOADED = False


def _get_ffmpeg() -> Optional[str]:
    global _FFMPEG_PATH, _FFMPEG_LOADED
    if _FFMPEG_LOADED:
        return _FFMPEG_PATH
    _FFMPEG_LOADED = True
    # Priorite 1 : imageio_ffmpeg bundle dans l'app
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if Path(path).is_file():
            _FFMPEG_PATH = path
            return _FFMPEG_PATH
    except Exception:  # noqa: BLE001
        pass
    # Priorite 2 : ffmpeg systeme (PATH)
    try:
        import shutil
        found = shutil.which("ffmpeg")
        if found:
            _FFMPEG_PATH = found
            return _FFMPEG_PATH
    except Exception:  # noqa: BLE001
        pass
    return None


def _cache_key(video_path: Path, offset: float = 1.0, size: int = 256) -> Optional[str]:
    """Cle de cache basee sur (chemin abs + mtime + taille + offset + size).

    Compat : si offset=1.0 et size=256, on garde l'ancienne forme du hash
    (sans suffixe) pour reutiliser les caches existants. Pour les autres
    combinaisons (multi-frames embedding), nouveau format avec suffixe.
    """
    try:
        st = video_path.stat()
    except OSError:
        return None
    if abs(offset - 1.0) < 1e-9 and size == 256:
        # Forme historique (compat avec caches v1.2.4 - v1.2.9)
        data = f"{video_path.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    else:
        data = f"{video_path.resolve()}|{st.st_mtime_ns}|{st.st_size}|t{offset:.2f}|s{size}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:24]


def _extract_frame(video_path: Path, offset_seconds: float, size: int) -> Optional[Path]:
    """Extrait UNE frame d'une video a un offset donne, cache sur disque.

    Returns: Path vers le fichier JPG dans le cache, ou None si echec.
    """
    if not video_path.is_file():
        return None

    key = _cache_key(video_path, offset_seconds, size)
    if key is None:
        return None

    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None

    cache_file = CACHE_DIR / f"{key}.jpg"
    if cache_file.is_file() and cache_file.stat().st_size > 0:
        return cache_file

    ffmpeg = _get_ffmpeg()
    if not ffmpeg:
        return None

    # Formatage HH:MM:SS pour ffmpeg -ss
    ss_str = f"{offset_seconds:.2f}"
    vf = f"scale='min({size},iw)':'min({size},ih)':force_original_aspect_ratio=decrease"
    cmd = [
        ffmpeg,
        "-loglevel", "error",
        "-ss", ss_str,
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", vf,
        "-q:v", "5",
        "-y",
        str(cache_file),
    ]

    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x08000000  # CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=15,
            creationflags=creationflags,
        )
        if result.returncode != 0 or not cache_file.is_file() or cache_file.stat().st_size == 0:
            # Echec : video plus courte que l'offset. Retente sans -ss (frame 0).
            cmd_no_seek = [c for c in cmd if c not in ("-ss", ss_str)]
            try:
                result2 = subprocess.run(
                    cmd_no_seek,
                    capture_output=True,
                    timeout=15,
                    creationflags=creationflags,
                )
                if result2.returncode != 0 or not cache_file.is_file() or cache_file.stat().st_size == 0:
                    try:
                        cache_file.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return None
            except Exception:  # noqa: BLE001
                return None
        return cache_file
    except Exception:  # noqa: BLE001
        try:
            cache_file.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def get_video_thumbnail(video_path: Path, size: int = 256) -> Optional[Path]:
    """Retourne le chemin d'une image JPG thumbnail de la video pour preview UI.

    1 frame a 1s (souvent plus interessant que la 1ere frame qui peut etre
    noire / fade-in). Cache sur disque, appels suivants quasi-instantanes.
    Si ffmpeg pas dispo ou extraction echoue : None (l'UI affiche badge VIDEO).
    """
    return _extract_frame(video_path, 1.0, size)


def get_video_frames_for_embedding(video_path: Path, n_frames: int = 3, size: int = 384) -> list[Path]:
    """Extrait N frames pour le clustering (1 seule frame est trop biaisee
    par les intros noires / logos / fade-in).

    Strategie : 3 frames a 1s, 5s, 15s. Couvre intro / contenu / transitions.
    Pour des videos courtes (< 15s par ex), seules les frames qui marchent
    sont retournees. La liste peut donc avoir 1, 2 ou 3 elements.

    Returns: liste de paths vers les frames JPG en cache. Vide si tout
    a echoue (video corrompue, format inconnu, ffmpeg absent...).
    """
    if not video_path.is_file():
        return []
    offsets = [1.0, 5.0, 15.0][:n_frames]
    paths: list[Path] = []
    for offset in offsets:
        frame = _extract_frame(video_path, offset, size)
        if frame is not None:
            paths.append(frame)
    # Si tout a echoue (videos courtes ou tres courtes), fallback : frame 0
    if not paths:
        fallback = _extract_frame(video_path, 0.0, size)
        if fallback is not None:
            paths.append(fallback)
    return paths


def is_video_thumb_available() -> bool:
    """True si ffmpeg est disponible (donc les previews vont marcher)."""
    return _get_ffmpeg() is not None

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


def _cache_key(video_path: Path) -> Optional[str]:
    """Cle de cache basee sur le chemin absolu + mtime + taille."""
    try:
        st = video_path.stat()
    except OSError:
        return None
    data = f"{video_path.resolve()}|{st.st_mtime_ns}|{st.st_size}"
    return hashlib.sha256(data.encode("utf-8")).hexdigest()[:24]


def get_video_thumbnail(video_path: Path, size: int = 256) -> Optional[Path]:
    """Retourne le chemin d'une image JPG thumbnail de la video, ou None.

    L'image est cachee sur disque ; les appels suivants sur la meme video
    sont quasi-instantanes (juste un stat() + return).

    Si ffmpeg n'est pas dispo ou si l'extraction echoue, retourne None.
    L'appelant doit gerer ce cas (typiquement, afficher le badge 'VIDEO').
    """
    if not video_path.is_file():
        return None

    key = _cache_key(video_path)
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

    # Construit la commande ffmpeg :
    #   -ss 00:00:01     : seek a 1s (souvent plus interessant que la 1ere frame
    #                      qui peut etre noire / fade-in)
    #   -i path          : input video
    #   -vframes 1       : une seule frame
    #   -vf scale=...    : resize en gardant le ratio, max 'size' sur le grand cote
    #   -q:v 5           : qualite JPG (1=meilleure, 31=pire, 5 est un bon compromis)
    #   -y               : overwrite output sans demander
    #   -loglevel error  : pas de spam stdout
    vf = f"scale='min({size},iw)':'min({size},ih)':force_original_aspect_ratio=decrease"
    cmd = [
        ffmpeg,
        "-loglevel", "error",
        "-ss", "00:00:01",
        "-i", str(video_path),
        "-vframes", "1",
        "-vf", vf,
        "-q:v", "5",
        "-y",
        str(cache_file),
    ]

    # Note CREATE_NO_WINDOW : empeche une fenetre cmd noire de flasher sur Windows
    creationflags = 0
    if sys.platform == "win32":
        creationflags = 0x08000000  # CREATE_NO_WINDOW

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=15,  # 15s max par video (large mais pas infini)
            creationflags=creationflags,
        )
        if result.returncode != 0 or not cache_file.is_file() or cache_file.stat().st_size == 0:
            # Echec : si on a essaye de seek a 1s mais la video est < 1s, retente
            # sans le -ss (prend la 1ere frame).
            cmd_no_seek = [c for c in cmd if c not in ("-ss", "00:00:01")]
            try:
                result2 = subprocess.run(
                    cmd_no_seek,
                    capture_output=True,
                    timeout=15,
                    creationflags=creationflags,
                )
                if result2.returncode != 0 or not cache_file.is_file() or cache_file.stat().st_size == 0:
                    # Echec definitif : supprime le fichier vide si y en a un
                    try:
                        cache_file.unlink(missing_ok=True)
                    except OSError:
                        pass
                    return None
            except Exception:  # noqa: BLE001
                return None
        return cache_file
    except Exception:  # noqa: BLE001
        # Timeout, ffmpeg manquant, etc.
        try:
            cache_file.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def is_video_thumb_available() -> bool:
    """True si ffmpeg est disponible (donc les previews vont marcher)."""
    return _get_ffmpeg() is not None

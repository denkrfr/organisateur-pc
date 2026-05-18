"""Pipeline de dedup porte de l'app Android (V2.1.0).

Etapes :
  1. fetch_assets       liste les fichiers
  2. quick_hash         hash partiel rapide (32 KB par fichier)
  3. group_by_hash      candidats par quick-hash
  4. verify_byte_by_byte confirme l'identite exacte des candidats
  5. compute_a_hashes   perceptual hash pour les quasi-doublons
  6. cluster_by_a_hash  regroupe par distance de Hamming
  7. merge              union exact + quasi, tri par espace recuperable
"""

from __future__ import annotations
import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Optional

from PIL import Image
import imagehash

from .models import Asset, DupGroup
from . import docs

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
QUICK_HASH_BYTES = 16 * 1024  # 16 KB head + 16 KB tail
MIN_FILE_SIZE = 1024  # ignorer les fichiers < 1 KB (icones, thumbnails)
VERIFY_CHUNK = 1024 * 1024  # 1 MB par lecture pour byte-by-byte

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".heic", ".heif", ".tiff", ".tif"}
DOC_EXTS = {".pdf", ".docx", ".xlsx"}
SUPPORTED_EXTS = IMAGE_EXTS | DOC_EXTS

QUASI_THRESHOLD_PHOTO = 5
QUASI_THRESHOLD_SCREENSHOT = 7

# Parallelisme : I/O-bound, le GIL n'est pas un probleme. On garde modeste pour
# ne pas saturer le disque.
HASH_WORKERS = 8           # quick-hash (lecture 32 KB par fichier)
AHASH_WORKERS = 4          # aHash (Pillow decode + numpy)
TEXT_WORKERS = 4           # extraction PDF/DOCX/XLSX


ProgressCb = Callable[[int, int, str], None]
CancelCheck = Callable[[], bool]  # retourne True si on doit annuler


# Sentinel par defaut : jamais annule
def _never_cancel() -> bool:
    return False


class _Cancelled(Exception):
    """Leve quand l'utilisateur a demande l'arret du scan."""
    pass


def _check_cancel(cancel_check: CancelCheck) -> None:
    if cancel_check():
        raise _Cancelled()


def _is_screenshot(path: Path) -> bool:
    """Heuristique nom + chemin pour donner un threshold plus permissif."""
    s = str(path).lower()
    return "screenshot" in s or "screen-shot" in s or "screen_shot" in s


# ---------------------------------------------------------------------------
# 1. Liste des fichiers
# ---------------------------------------------------------------------------
def fetch_assets(
    folders: Iterable[Path],
    on_progress: ProgressCb,
    cancel_check: CancelCheck = _never_cancel,
) -> list[Asset]:
    """Liste recursivement les fichiers supportes des dossiers donnes."""
    assets: list[Asset] = []
    folder_list = list(folders)
    on_progress(0, 0, "Liste des fichiers...")
    for folder in folder_list:
        for path in folder.rglob("*"):
            _check_cancel(cancel_check)
            if not path.is_file():
                continue
            if path.suffix.lower() not in SUPPORTED_EXTS:
                continue
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size < MIN_FILE_SIZE:
                continue
            kind = docs.kind_of(path)
            assets.append(Asset(path=path, size=size, kind=kind))
            if len(assets) % 100 == 0:
                on_progress(len(assets), 0, f"Liste : {len(assets)} fichiers")
    on_progress(len(assets), len(assets), f"Liste : {len(assets)} fichiers")
    return assets


# ---------------------------------------------------------------------------
# 2. Quick hash
# ---------------------------------------------------------------------------
def _quick_hash_file(path: Path, size: int) -> str | None:
    """SHA256(head 16KB + tail 16KB + size) — equivalent de l'Android."""
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            if size <= 2 * QUICK_HASH_BYTES:
                h.update(f.read())
            else:
                h.update(f.read(QUICK_HASH_BYTES))
                f.seek(-QUICK_HASH_BYTES, 2)
                h.update(f.read(QUICK_HASH_BYTES))
        h.update(b"|" + str(size).encode())
        return h.hexdigest()
    except OSError:
        return None


def compute_quick_hashes(
    assets: list[Asset],
    on_progress: ProgressCb,
    cancel_check: CancelCheck = _never_cancel,
) -> list[Asset]:
    """Parallelise sur HASH_WORKERS threads (I/O-bound, GIL OK)."""
    out: list[Asset] = []
    total = len(assets)
    done = 0
    if total == 0:
        return out

    def _hash_one(a: Asset) -> Asset:
        a.quick_hash = _quick_hash_file(a.path, a.size)
        return a

    with ThreadPoolExecutor(max_workers=HASH_WORKERS) as pool:
        futures = {pool.submit(_hash_one, a): a for a in assets}
        for fut in as_completed(futures):
            if cancel_check():
                # Annule les pending
                for f in futures:
                    f.cancel()
                raise _Cancelled()
            try:
                a = fut.result()
                if a.quick_hash is not None:
                    out.append(a)
            except Exception:  # noqa: BLE001
                pass
            done += 1
            if done % 50 == 0 or done == total:
                on_progress(done, total, f"Quick-hash : {done} / {total}")
    return out


# ---------------------------------------------------------------------------
# 3. Group by quick hash (candidats exacts)
# ---------------------------------------------------------------------------
def group_by_hash(assets: list[Asset]) -> list[list[Asset]]:
    buckets: dict[str, list[Asset]] = {}
    for a in assets:
        if a.quick_hash is None:
            continue
        buckets.setdefault(a.quick_hash, []).append(a)
    return [items for items in buckets.values() if len(items) >= 2]


# ---------------------------------------------------------------------------
# 4. Verification byte-by-byte (Czkawka-style)
# ---------------------------------------------------------------------------
def _files_are_identical(a: Path, b: Path, size: int) -> bool:
    """Compare 2 fichiers par chunks de 1 MB. Stoppe a la 1ere difference."""
    try:
        with a.open("rb") as fa, b.open("rb") as fb:
            remaining = size
            while remaining > 0:
                chunk_size = min(VERIFY_CHUNK, remaining)
                ca = fa.read(chunk_size)
                cb = fb.read(chunk_size)
                if ca != cb:
                    return False
                remaining -= len(ca)
                if not ca:
                    break
        return True
    except OSError:
        return False


def verify_groups(
    candidates: list[list[Asset]],
    on_progress: ProgressCb,
    cancel_check: CancelCheck = _never_cancel,
) -> list[DupGroup]:
    """Pour chaque groupe candidat, separe en sous-groupes byte-identiques."""
    out: list[DupGroup] = []
    total = len(candidates)
    for idx, items in enumerate(candidates):
        _check_cancel(cancel_check)
        on_progress(idx, total, f"Verification {idx + 1} / {total}")
        buckets: list[list[Asset]] = []
        for item in items:
            _check_cancel(cancel_check)
            placed = False
            for bucket in buckets:
                if _files_are_identical(bucket[0].path, item.path, item.size):
                    bucket.append(item)
                    placed = True
                    break
            if not placed:
                buckets.append([item])
        for b in buckets:
            if len(b) >= 2:
                out.append(
                    DupGroup(
                        items=sorted(b, key=lambda a: a.size, reverse=True),
                        kind="exact",
                        representative_hash=b[0].quick_hash or "",
                    )
                )
    on_progress(total, total, f"Verification {total} / {total}")
    return out


# ---------------------------------------------------------------------------
# 5. Perceptual hash (aHash) via imagehash
# ---------------------------------------------------------------------------
def _compute_a_hash(path: Path) -> int | None:
    """8x8 average hash, retourne un int 64-bit. None si decodage impossible."""
    try:
        with Image.open(path) as img:
            ahash = imagehash.average_hash(img, hash_size=8)
        # imagehash retourne un objet ImageHash, on convertit en int 64-bit
        return int(str(ahash), 16)
    except (OSError, Image.UnidentifiedImageError, ValueError):
        return None


def compute_a_hashes(
    assets: list[Asset],
    on_progress: ProgressCb,
    cancel_check: CancelCheck = _never_cancel,
) -> list[Asset]:
    """Calcule le aHash sur les images uniquement, en parallele."""
    out: list[Asset] = []
    images = [a for a in assets if a.kind == "image"]
    total = len(images)
    done = 0
    if total == 0:
        return out

    def _hash_one(a: Asset) -> Asset:
        a.a_hash = _compute_a_hash(a.path)
        return a

    with ThreadPoolExecutor(max_workers=AHASH_WORKERS) as pool:
        futures = {pool.submit(_hash_one, a): a for a in images}
        for fut in as_completed(futures):
            if cancel_check():
                for f in futures:
                    f.cancel()
                raise _Cancelled()
            try:
                a = fut.result()
                if a.a_hash is not None:
                    out.append(a)
            except Exception:  # noqa: BLE001
                pass
            done += 1
            if done % 20 == 0 or done == total:
                on_progress(done, total, f"Quasi-doublons (images) : {done} / {total}")
    return out


def compute_text_hashes(
    assets: list[Asset],
    on_progress: ProgressCb,
    cancel_check: CancelCheck = _never_cancel,
) -> list[Asset]:
    """Extrait le texte des docs et calcule un fingerprint, en parallele."""
    out: list[Asset] = []
    docs_only = [a for a in assets if a.kind in ("pdf", "docx", "xlsx")]
    total = len(docs_only)
    done = 0
    if total == 0:
        return out

    def _hash_one(a: Asset) -> Asset:
        text = docs.extract_text(a.path, max_chars=20_000)
        if text:
            a.text_hash = docs.text_fingerprint(text)
        return a

    with ThreadPoolExecutor(max_workers=TEXT_WORKERS) as pool:
        futures = {pool.submit(_hash_one, a): a for a in docs_only}
        for fut in as_completed(futures):
            if cancel_check():
                for f in futures:
                    f.cancel()
                raise _Cancelled()
            try:
                a = fut.result()
                if a.text_hash is not None:
                    out.append(a)
            except Exception:  # noqa: BLE001
                pass
            done += 1
            if done % 5 == 0 or done == total:
                on_progress(done, total, f"Quasi-doublons (docs) : {done} / {total}")
    return out


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# ---------------------------------------------------------------------------
# 6. Cluster by aHash (quasi-doublons)
# ---------------------------------------------------------------------------
def cluster_by_a_hash(assets: list[Asset]) -> list[list[Asset]]:
    """Regroupe les assets par distance de Hamming sur leur aHash. O(n*k)
    ou k = nb de clusters, en pratique tres rapide vs O(n^2)."""
    clusters: list[list[Asset]] = []
    for a in assets:
        if a.a_hash is None:
            continue
        threshold = (
            QUASI_THRESHOLD_SCREENSHOT if _is_screenshot(a.path) else QUASI_THRESHOLD_PHOTO
        )
        placed = False
        for cluster in clusters:
            rep = cluster[0]
            if rep.a_hash is not None and _hamming(a.a_hash, rep.a_hash) <= threshold:
                cluster.append(a)
                placed = True
                break
        if not placed:
            clusters.append([a])
    return clusters


def cluster_by_text_hash(assets: list[Asset]) -> list[list[Asset]]:
    """Groupe les docs par fingerprint identique (match exact du texte normalise)."""
    buckets: dict[str, list[Asset]] = {}
    for a in assets:
        if a.text_hash is None:
            continue
        buckets.setdefault(a.text_hash, []).append(a)
    return [items for items in buckets.values() if len(items) >= 2]


def build_quasi_groups(
    clusters: list[list[Asset]], exact_groups: list[DupGroup]
) -> list[DupGroup]:
    """Skip les clusters dont tous les items sont deja dans le meme exact group."""
    exact_idx_of: dict[Path, int] = {}
    for idx, g in enumerate(exact_groups):
        for it in g.items:
            exact_idx_of[it.path] = idx

    out: list[DupGroup] = []
    for cluster in clusters:
        if len(cluster) < 2:
            continue
        idxs = {exact_idx_of.get(it.path, -1) for it in cluster}
        if len(idxs) == 1 and (only := next(iter(idxs))) >= 0:
            continue  # cluster entierement contenu dans un seul exact group
        items = sorted(cluster, key=lambda a: a.size, reverse=True)
        rep = items[0]
        if rep.a_hash is not None:
            rep_hash = f"~{rep.a_hash:016x}"
        elif rep.text_hash is not None:
            rep_hash = f"~txt:{rep.text_hash[:12]}"
        else:
            rep_hash = "~?"
        out.append(
            DupGroup(
                items=items,
                kind="quasi",
                representative_hash=rep_hash,
            )
        )
    return out


# ---------------------------------------------------------------------------
# Pipeline orchestre
# ---------------------------------------------------------------------------
def run_pipeline(
    folders: Iterable[Path],
    include_p_hash: bool,
    on_progress: ProgressCb,
    deleted_paths: set[Path] | None = None,
    cancel_check: CancelCheck = _never_cancel,
) -> list[DupGroup]:
    """Execute le pipeline complet et retourne les groupes mergees + tries.
    Peut etre annule a tout moment via cancel_check : leve _Cancelled, qui doit
    etre attrapee par le caller (ScanWorker)."""
    assets = fetch_assets(folders, on_progress, cancel_check)
    if deleted_paths:
        assets = [a for a in assets if a.path not in deleted_paths]
    hashed = compute_quick_hashes(assets, on_progress, cancel_check)
    candidates = group_by_hash(hashed)
    exact_groups = verify_groups(candidates, on_progress, cancel_check)

    quasi_groups: list[DupGroup] = []
    if include_p_hash:
        # Images : aHash + Hamming
        with_a_hash = compute_a_hashes(hashed, on_progress, cancel_check)
        clusters = cluster_by_a_hash(with_a_hash)
        quasi_groups = build_quasi_groups(clusters, exact_groups)

        # Docs : fingerprint texte
        with_text = compute_text_hashes(hashed, on_progress, cancel_check)
        doc_clusters = cluster_by_text_hash(with_text)
        quasi_groups.extend(build_quasi_groups(doc_clusters, exact_groups))

    merged = exact_groups + quasi_groups
    merged.sort(key=lambda g: g.total_recoverable, reverse=True)
    return merged

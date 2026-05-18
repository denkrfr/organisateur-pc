"""Clustering visuel : regroupe les fichiers similaires sans aucun
apprentissage prealable. L'user n'a qu'a nommer chaque groupe.

Algo : greedy clustering par similarite cosinus sur les embeddings CLIP.
  1. Pour chaque fichier, calculer son embedding (image -> CLIP, doc -> E5)
  2. Prendre le premier fichier non assigne, en faire un nouveau cluster
  3. Y ajouter tous les fichiers non assignes >= threshold de similarite
  4. Recommencer jusqu'a ce que tous soient assignes

Tries : cluster les plus gros en premier (utiles pour le user).
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

from . import docs
from . import embeddings as _emb


ProgressCb = Callable[[int, int, str], None]


@dataclass
class Cluster:
    """Un groupe de fichiers similaires."""
    items: list[Path] = field(default_factory=list)
    kind: str = "image"  # 'image' ou 'doc'
    suggested_name: str = ""  # nom propose (mode API uniquement, sinon vide)

    @property
    def size(self) -> int:
        return len(self.items)

    @property
    def total_bytes(self) -> int:
        total = 0
        for p in self.items:
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total


def _embed_image(path: Path) -> Optional[np.ndarray]:
    """Embedding CLIP image (avec cache disque)."""
    if not _emb.embeddings_available():
        return None
    return _emb.ClipEmbedder.get().encode_image(path)


def _embed_doc(path: Path) -> Optional[np.ndarray]:
    """Embedding E5 sur le texte extrait (pour les docs)."""
    if not _emb.embeddings_available():
        return None
    text = docs.extract_text(path, max_chars=5000) or ""
    if len(text.strip()) < 20:
        return None
    return _emb.E5Embedder.get().encode(text)


def _greedy_cluster(
    paths: list[Path],
    embeds: dict[Path, np.ndarray],
    threshold: float,
    on_progress: ProgressCb,
    progress_offset: int,
    progress_total: int,
) -> list[list[Path]]:
    """Clustering greedy : pour chaque fichier non place, demarre un cluster
    et y ajoute tous les fichiers similaires (>= threshold cosinus).
    """
    clusters: list[list[Path]] = []
    used: set[Path] = set()
    # On utilise l'ordre des paths pour la stabilite. Le cluster prend
    # le premier non utilise comme centre.
    for i, p in enumerate(paths):
        if p in used or p not in embeds:
            continue
        center_vec = embeds[p]
        cluster = [p]
        used.add(p)
        # Compare avec tous les autres non utilises
        for q in paths:
            if q in used or q not in embeds:
                continue
            sim = float(np.dot(center_vec, embeds[q]))
            if sim >= threshold:
                cluster.append(q)
                used.add(q)
        clusters.append(cluster)
        if (i + 1) % 50 == 0:
            on_progress(progress_offset + i + 1, progress_total,
                        f"Clustering : {len(clusters)} groupes formes")
    return clusters


def cluster_files(
    paths: list[Path],
    image_threshold: float = 0.82,
    text_threshold: float = 0.88,
    on_progress: Optional[ProgressCb] = None,
) -> list[Cluster]:
    """Pipeline complet : embed -> cluster -> tri par taille.

    Args:
        paths: fichiers a clusterer (images + docs melanges)
        image_threshold: seuil de similarite cosinus pour images (0.82 = strict)
        text_threshold: seuil pour docs (0.88 plus strict car E5 a baseline elevee)
        on_progress: callback (current, total, label)

    Returns:
        Liste des Cluster, tries par taille decroissante.
        Les singletons (clusters d'1 seul fichier) sont inclus aussi (cluster.size=1).
    """
    if on_progress is None:
        on_progress = lambda *_: None

    total = len(paths)
    on_progress(0, total, "Calcul des embeddings...")

    # Phase 1 : separer images / docs
    images = [p for p in paths if docs.kind_of(p) == "image"]
    docs_only = [p for p in paths if docs.kind_of(p) in ("pdf", "docx", "xlsx")]

    # Phase 2 : embeddings
    image_embeds: dict[Path, np.ndarray] = {}
    for i, p in enumerate(images):
        v = _embed_image(p)
        if v is not None:
            image_embeds[p] = v
        on_progress(i + 1, total, f"Embedding image {i + 1}/{len(images)}")

    doc_embeds: dict[Path, np.ndarray] = {}
    for i, p in enumerate(docs_only):
        v = _embed_doc(p)
        if v is not None:
            doc_embeds[p] = v
        on_progress(len(images) + i + 1, total,
                    f"Embedding doc {i + 1}/{len(docs_only)}")

    # Phase 3 : cluster images
    on_progress(total, total, "Clustering...")
    image_clusters_raw = _greedy_cluster(
        images, image_embeds, image_threshold,
        on_progress, total, total,
    )
    doc_clusters_raw = _greedy_cluster(
        docs_only, doc_embeds, text_threshold,
        on_progress, total, total,
    )

    # Phase 4 : wrap dans Cluster + trier par taille decroissante
    result: list[Cluster] = []
    for items in image_clusters_raw:
        result.append(Cluster(items=items, kind="image"))
    for items in doc_clusters_raw:
        result.append(Cluster(items=items, kind="doc"))

    # Files unsupported (kind 'other' or pas d'embedding) -> singletons
    embedded = set(image_embeds) | set(doc_embeds)
    for p in paths:
        if p not in embedded:
            result.append(Cluster(items=[p], kind="other"))

    result.sort(key=lambda c: -c.size)
    on_progress(total, total, f"Termine : {len(result)} groupes")
    return result

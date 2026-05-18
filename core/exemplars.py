"""Stockage des exemples par dossier pour le tri semantique.

Quand l'utilisateur deplace un fichier vers un dossier (ou ajoute un
exemplar manuellement), on calcule son embedding et on l'ajoute a la
collection de ce dossier. Pour classer un nouveau fichier, on compare son
embedding au centroide de chaque dossier connu.

Structure disque dans ~/.organisateur-pc/exemplars/ :
  - image_exemplars.json : { folder_name: [list of (path, fingerprint)] }
  - text_exemplars.json  : pareil pour texte (docs, OCR)
  - image_centroids.npz  : matrice (N_folders, 512) - cache des centroides CLIP
  - text_centroids.npz   : matrice (N_folders, 384) - cache des centroides E5

On garde max EXEMPLARS_PER_FOLDER exemples par dossier (les plus recents).
Quand on ajoute un exemplar, on recalcule le centroide du dossier.
"""

from __future__ import annotations
import json
import threading
from pathlib import Path
from typing import Optional

import numpy as np

from . import embeddings


EXEMPLARS_PER_FOLDER = 50  # plafond pour ne pas exploser le disque


def _store_dir() -> Path:
    d = Path.home() / ".organisateur-pc" / "exemplars"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _img_json() -> Path:
    return _store_dir() / "image_exemplars.json"


def _txt_json() -> Path:
    return _store_dir() / "text_exemplars.json"


def _img_centroids() -> Path:
    return _store_dir() / "image_centroids.npz"


def _txt_centroids() -> Path:
    return _store_dir() / "text_centroids.npz"


# ---------------------------------------------------------------------------
# Store : 1 instance singleton (locks pour thread safety)
# ---------------------------------------------------------------------------
class ExemplarStore:
    _instance: Optional["ExemplarStore"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        # path -> embedding vector (in-memory cache des exemplars)
        # Pour image: {folder_name: list[ndarray 512]}, idem text 384
        self._img_vectors: dict[str, list[np.ndarray]] = {}
        self._txt_vectors: dict[str, list[np.ndarray]] = {}
        # Centroides pre-calcules
        self._img_centroids: dict[str, np.ndarray] = {}
        self._txt_centroids: dict[str, np.ndarray] = {}
        self._mutex = threading.RLock()
        self._load_from_disk()

    @classmethod
    def get(cls) -> "ExemplarStore":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def _load_from_disk(self) -> None:
        """Recharge les centroides depuis le cache npz s'il existe."""
        for f, target in [(_img_centroids(), self._img_centroids),
                          (_txt_centroids(), self._txt_centroids)]:
            if not f.exists():
                continue
            try:
                data = np.load(str(f), allow_pickle=False)
                for name in data.files:
                    target[name] = data[name].astype(np.float32)
            except Exception:  # noqa: BLE001
                continue
        # Charge aussi les listes d'exemplars individuelles (depuis disk cache)
        for jf, target in [(_img_json(), self._img_vectors),
                           (_txt_json(), self._txt_vectors)]:
            if not jf.exists():
                continue
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for folder, entries in data.items():
                vectors: list[np.ndarray] = []
                for entry in entries:
                    if isinstance(entry, dict) and "vec" in entry:
                        vectors.append(np.array(entry["vec"], dtype=np.float32))
                if vectors:
                    target[folder] = vectors

    def _atomic_write_bytes(self, target: Path, data: bytes) -> None:
        """Ecriture atomique : tmpfile + os.replace."""
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            tmp.write_bytes(data)
            import os
            os.replace(str(tmp), str(target))
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    def _save_to_disk(self) -> None:
        """Persistance atomique : on ecrit dans un .tmp puis on rename."""
        # Centroides (npz)
        for centroids, target in [(self._img_centroids, _img_centroids()),
                                  (self._txt_centroids, _txt_centroids())]:
            if not centroids:
                # Si vide et fichier existe, supprime
                if target.exists():
                    try:
                        target.unlink()
                    except OSError:
                        pass
                continue
            import io
            buf = io.BytesIO()
            try:
                np.savez(buf, **centroids)
                self._atomic_write_bytes(target, buf.getvalue())
            except (OSError, ValueError):
                pass
        # Listes d'exemplars (json)
        for jf, src in [(_img_json(), self._img_vectors),
                        (_txt_json(), self._txt_vectors)]:
            serial: dict[str, list[dict]] = {}
            for folder, vectors in src.items():
                serial[folder] = [{"vec": v.tolist()} for v in vectors]
            try:
                data = json.dumps(serial, ensure_ascii=False).encode("utf-8")
                self._atomic_write_bytes(jf, data)
            except (OSError, TypeError):
                pass

    def _recompute_centroid(self, folder: str, kind: str) -> None:
        """kind = 'img' ou 'txt'. Met a jour le centroide a partir des vecteurs."""
        if kind == "img":
            vectors = self._img_vectors.get(folder, [])
            target = self._img_centroids
        else:
            vectors = self._txt_vectors.get(folder, [])
            target = self._txt_centroids
        if not vectors:
            target.pop(folder, None)
            return
        mean = np.mean(np.stack(vectors), axis=0)
        norm = np.linalg.norm(mean)
        if norm > 1e-9:
            mean = mean / norm
        target[folder] = mean.astype(np.float32)

    # ------------------------------------------------------------------
    # API : ajouter un exemplar
    # ------------------------------------------------------------------
    def add_image_exemplar(self, folder: str, path: Path, *, defer_save: bool = False) -> bool:
        """Calcule l'embedding CLIP et ajoute au dossier. Retourne True si OK.
        defer_save=True : ne persiste pas immediat (utile pour batch). Appeler
        flush() apres pour ecrire le tout sur disque en 1 fois."""
        vec = embeddings.ClipEmbedder.get().encode_image(path)
        if vec is None:
            return False
        with self._mutex:
            lst = self._img_vectors.setdefault(folder, [])
            lst.append(vec)
            if len(lst) > EXEMPLARS_PER_FOLDER:
                self._img_vectors[folder] = lst[-EXEMPLARS_PER_FOLDER:]
            self._recompute_centroid(folder, "img")
            if not defer_save:
                self._save_to_disk()
        return True

    def add_text_exemplar(self, folder: str, text: str, *, defer_save: bool = False) -> bool:
        """Calcule l'embedding E5 du texte et l'ajoute au dossier."""
        vec = embeddings.E5Embedder.get().encode(text)
        if vec is None:
            return False
        with self._mutex:
            lst = self._txt_vectors.setdefault(folder, [])
            lst.append(vec)
            if len(lst) > EXEMPLARS_PER_FOLDER:
                self._txt_vectors[folder] = lst[-EXEMPLARS_PER_FOLDER:]
            self._recompute_centroid(folder, "txt")
            if not defer_save:
                self._save_to_disk()
        return True

    def flush(self) -> None:
        """Force la sauvegarde sur disque. A appeler apres un batch d'ajouts
        avec defer_save=True."""
        with self._mutex:
            self._save_to_disk()

    # ------------------------------------------------------------------
    # API : ajouter un exemplar texte = nom de dossier lui-meme
    # ------------------------------------------------------------------
    def seed_folder_name(self, folder: str) -> bool:
        """Ajoute le NOM du dossier comme exemplar texte. Permet de matcher
        un fichier dont le contenu mentionne ce nom, meme sans deplacement
        anterieur. Idempotent (ne re-ajoute pas si centroid existe)."""
        if folder in self._txt_centroids:
            return True
        # Le nom du dossier peut etre "Bank/Boursorama" -> on prend tout
        clean = folder.replace("/", " ").replace("\\", " ").strip()
        return self.add_text_exemplar(folder, clean)

    # ------------------------------------------------------------------
    # API : query
    # ------------------------------------------------------------------
    def best_image_match(self, path: Path, top_n: int = 3) -> list[tuple[str, float]]:
        """Top_n dossiers les plus proches de l'image. Score = max-of-exemplars-image.
        IMPORTANT : on ne propose QUE des dossiers ayant des exemplars IMAGE reels
        (pas le seeding du nom de dossier). Sinon on inventerait pour des noms propres."""
        if not self._img_vectors:
            return []
        vec = embeddings.ClipEmbedder.get().encode_image(path)
        if vec is None:
            return []
        with self._mutex:
            scores: dict[str, float] = {}
            for folder, vectors in self._img_vectors.items():
                if not vectors:
                    continue
                max_sim = max(float(np.dot(vec, v)) for v in vectors)
                centroid = self._img_centroids.get(folder)
                if centroid is not None:
                    centroid_s = float(np.dot(vec, centroid))
                    scores[folder] = 0.6 * max_sim + 0.4 * centroid_s
                else:
                    scores[folder] = max_sim
        sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
        return sorted_scores[:top_n]

    def best_text_match(self, text: str, top_n: int = 3, min_real_exemplars: int = 1) -> list[tuple[str, float]]:
        """Top_n dossiers via texte. Avec max-of-exemplars + centroide.
        On ignore les dossiers qui n'ont que le seed du nom (1 seul exemplar = juste le nom)
        car ces matches sont generalement du bruit pour des noms propres."""
        if not self._txt_vectors:
            return []
        vec = embeddings.E5Embedder.get().encode(text)
        if vec is None:
            return []
        with self._mutex:
            scores: dict[str, float] = {}
            for folder, vectors in self._txt_vectors.items():
                if len(vectors) < min_real_exemplars:
                    continue
                max_sim = max(float(np.dot(vec, v)) for v in vectors)
                centroid = self._txt_centroids.get(folder)
                if centroid is not None:
                    centroid_s = float(np.dot(vec, centroid))
                    scores[folder] = 0.6 * max_sim + 0.4 * centroid_s
                else:
                    scores[folder] = max_sim
        sorted_scores = sorted(scores.items(), key=lambda x: -x[1])
        return sorted_scores[:top_n]

    def best_match_combined(
        self,
        image_path: Optional[Path],
        text: Optional[str],
        top_n: int = 3,
    ) -> list[tuple[str, float]]:
        """Combine image + texte. Si les 2 dispos, somme ponderee des scores
        normalises par dossier. Sinon, retourne ce qui est dispo."""
        img_scores = dict(self.best_image_match(image_path, top_n=20)) if image_path else {}
        txt_scores = dict(self.best_text_match(text, top_n=20)) if text else {}
        if not img_scores and not txt_scores:
            return []
        all_folders = set(img_scores) | set(txt_scores)
        out: list[tuple[str, float]] = []
        for f in all_folders:
            # Pondere : si on a les 2 signaux, on les moyenne. Sinon 70% du score dispo.
            si = img_scores.get(f)
            st = txt_scores.get(f)
            if si is not None and st is not None:
                score = 0.55 * si + 0.45 * st
            elif si is not None:
                score = 0.85 * si
            else:
                score = 0.85 * st  # type: ignore[arg-type]
            out.append((f, score))
        out.sort(key=lambda x: -x[1])
        return out[:top_n]

    # ------------------------------------------------------------------
    # API : metadonnees
    # ------------------------------------------------------------------
    def known_folders(self) -> list[str]:
        with self._mutex:
            return sorted(set(self._img_centroids) | set(self._txt_centroids))

    def exemplar_count(self, folder: str) -> tuple[int, int]:
        """(nb_image_exemplars, nb_text_exemplars)"""
        with self._mutex:
            ni = len(self._img_vectors.get(folder, []))
            nt = len(self._txt_vectors.get(folder, []))
        return ni, nt

    def clear_folder(self, folder: str) -> None:
        with self._mutex:
            self._img_vectors.pop(folder, None)
            self._img_centroids.pop(folder, None)
            self._txt_vectors.pop(folder, None)
            self._txt_centroids.pop(folder, None)
            self._save_to_disk()

    def purge_text_only_seeds(self) -> int:
        """Nettoie les dossiers qui n'ont QUE 1 exemplar texte (= seed automatique
        du nom de dossier, qui s'avere etre du bruit pour les noms propres).
        Garde les dossiers avec au moins 2 exemplars texte ou des exemplars image.

        Retourne le nb de dossiers purges.
        """
        purged = 0
        with self._mutex:
            to_remove = []
            for folder, vectors in list(self._txt_vectors.items()):
                # Critere : 1 seul vecteur texte ET aucun vecteur image
                if len(vectors) == 1 and folder not in self._img_vectors:
                    to_remove.append(folder)
            for folder in to_remove:
                self._txt_vectors.pop(folder, None)
                self._txt_centroids.pop(folder, None)
                purged += 1
            if purged:
                self._save_to_disk()
        return purged

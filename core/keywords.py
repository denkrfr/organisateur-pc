"""Extraction de mots-cles representatifs d'un fichier (image ou document).

Pour les images : top-N tags de la liste CANDIDATE_TAGS pour lesquels CLIP
juge l'image semantiquement proche (zero-shot).
Pour les docs : top-N mots les plus frequents apres filtrage stopwords FR+EN.

Resultat : liste ordonnee de mots-cles, max top_n, vide si pas extractible.
"""

from __future__ import annotations
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Optional

from . import docs
from . import embeddings as _emb


# Tags candidats pour la classification image zero-shot.
# Couvre les grandes familles d'images (intentionnellement large pour rester
# utile sans biais metier).
CANDIDATE_TAGS = [
    # Scenes / lieux
    "photo de famille", "portrait", "groupe de personnes", "selfie",
    "paysage", "plage", "mer", "ville", "rue", "campagne", "montagne",
    "foret", "lac", "ciel", "nuit",
    # Objets
    "voiture", "moto", "velo", "bateau", "avion",
    "nourriture", "boisson", "plat cuisine", "dessert",
    "fleur", "plante", "arbre", "animal", "chat", "chien", "oiseau",
    "vetements", "chaussures", "bijou",
    "meuble", "chaise", "table", "lit", "canape", "lampe",
    # Travail / docs
    "document", "papier officiel", "facture", "recu", "ticket",
    "contrat", "rapport", "courrier", "lettre",
    "ecran ordinateur", "code informatique", "site internet",
    "graphique", "tableau de bord", "chart de trading",
    "presentation slides",
    # Communication
    "conversation messagerie", "whatsapp", "telegram", "messenger",
    "email", "reseau social", "facebook", "instagram", "tiktok",
    # Mediaart / design
    "design graphique", "logo", "illustration", "art moderne",
    "media art", "installation lumineuse", "led",
    # Divers
    "meme humoristique", "capture d ecran", "scan document",
    "art ancien", "musee", "exposition",
]


# Stopwords FR + EN (mots vides qu'on filtre dans l'extraction de keywords doc)
_STOPWORDS = {
    # FR
    "le", "la", "les", "un", "une", "des", "de", "du", "au", "aux",
    "et", "ou", "mais", "donc", "or", "car", "ni", "que", "qui", "quoi", "dont",
    "pour", "par", "avec", "sans", "sur", "sous", "dans", "vers", "chez",
    "ce", "cette", "ces", "cet", "son", "sa", "ses", "leur", "leurs",
    "mon", "ma", "mes", "ton", "ta", "tes", "notre", "nos", "votre", "vos",
    "je", "tu", "il", "elle", "on", "nous", "vous", "ils", "elles",
    "est", "etre", "ete", "suis", "es", "sont", "etais", "etait", "fut",
    "avoir", "ai", "as", "ont", "avait", "aura", "eu",
    "se", "sa", "lui", "leur", "moi", "toi", "soi",
    "pas", "ne", "non", "oui", "si", "tres", "plus", "moins", "trop",
    "tout", "tous", "toute", "toutes", "rien", "aucun", "aucune",
    "fait", "faire", "ferai", "doit", "doivent", "peut", "peuvent",
    "comme", "alors", "ainsi", "puis", "ensuite", "encore", "deja",
    # EN
    "the", "a", "an", "and", "or", "but", "for", "to", "of", "in", "on", "at",
    "by", "with", "from", "as", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "this", "that",
    "these", "those", "i", "you", "he", "she", "it", "we", "they", "what",
    "which", "who", "whom", "if", "then", "than", "so", "such", "not", "no",
    "yes", "very", "more", "less", "too", "any", "all", "some", "each",
    "every", "other", "new", "old", "first", "last", "only", "own", "same",
    "page", "pages",
    # Specifiques (mots courants dans les docs)
    "tel", "fax", "email", "mail",
}


def _normalize(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def _tokenize_doc(text: str) -> list[str]:
    """Tokenise un texte (doc/OCR) et filtre stopwords + nombres + courts."""
    tokens = re.findall(r"[a-zA-Z][a-zA-Z']{2,}", _normalize(text))
    return [t for t in tokens if t not in _STOPWORDS and len(t) >= 4]


def keywords_from_text(text: str, top_n: int = 6) -> list[str]:
    """Top-N mots les plus frequents (apres normalisation et filtrage)."""
    if not text or not text.strip():
        return []
    tokens = _tokenize_doc(text)
    if not tokens:
        return []
    counter = Counter(tokens)
    return [w for w, _ in counter.most_common(top_n)]


def keywords_from_image(path: Path, top_n: int = 6, min_score: float = 0.22) -> list[str]:
    """Top-N tags qui matchent semantiquement l'image via CLIP zero-shot.

    On encode l'image une fois, puis on calcule la similarite cosinus avec
    les embeddings cached des tags candidats (calcules au 1er appel).
    """
    if not _emb.embeddings_available():
        return []
    clip = _emb.ClipEmbedder.get()
    img_vec = clip.encode_image(path)
    if img_vec is None:
        return []

    # Cache des vecteurs tags
    global _TAG_VECS_CACHE
    try:
        _TAG_VECS_CACHE
    except NameError:
        _TAG_VECS_CACHE = None  # type: ignore[assignment]
    if _TAG_VECS_CACHE is None:
        import numpy as np
        vecs: dict[str, "np.ndarray"] = {}
        for tag in CANDIDATE_TAGS:
            v = clip.encode_text(f"a photo of {tag}")  # template CLIP standard
            if v is not None:
                vecs[tag] = v
        _TAG_VECS_CACHE = vecs  # type: ignore[assignment]

    import numpy as np
    scores = [
        (tag, float(np.dot(img_vec, vec)))
        for tag, vec in _TAG_VECS_CACHE.items()
    ]
    scores.sort(key=lambda x: -x[1])
    # Garde seulement les tags au-dessus du seuil + top_n
    return [tag for tag, s in scores[:top_n] if s >= min_score]


def keywords_for(path: Path, top_n: int = 6) -> list[str]:
    """Dispatch selon le type. Combine OCR + tags image si pertinent."""
    kind = docs.kind_of(path)
    if kind == "image":
        # Pour les images : zero-shot tags
        return keywords_from_image(path, top_n=top_n)
    if kind in ("pdf", "docx", "xlsx"):
        text = docs.extract_text(path, max_chars=8000) or ""
        return keywords_from_text(text, top_n=top_n)
    return []

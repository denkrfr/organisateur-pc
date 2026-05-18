"""Feature Tri (V1) : classe les screenshots par categorie en local.

Pipeline :
  1. detect_chart_trading   heuristique pixels pour les graphiques forex
  2. detect_text_keywords   OCR + regex (banque, conv, recus...) — STUB
  3. propose_folder         retourne (categorie, nom_dossier_propose)

L'utilisateur valide / corrige, ses choix sont memorises dans
sort_rules.json pour proposer la meme regle la prochaine fois.

Aucun reseau, tout local. Voir feature_trie_v3.md dans la memoire Claude
pour le detail de la spec.
"""

from __future__ import annotations
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from PIL import Image, ExifTags
import numpy as np

from . import docs
from . import embeddings as _emb


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DEFAULT_CATEGORIES = [
    "Bank",
    "Forex",
    "Conversations",
    "Receipts",
    "Tickets",
    "Memes",
    "Articles",
    "Emails",
    "Invoices",
    "CV",
    "Contracts",
    "Reports",
    "Spreadsheets",
    "Other",
]

# Regex de mots-cles par categorie. A enrichir au fur et a mesure des retours.
# Le matching est case-insensitive et fait sur le texte OCR du screenshot.
KEYWORD_RULES: dict[str, list[str]] = {
    "Bank": [
        r"\biban\b",
        r"\brib\b",
        r"\bsolde\b",
        r"\bvirement\b",
        r"\bcompte courant\b",
        r"credit mutuel|boursorama|societe generale|bnp|caisse d.epargne|la banque postale",
    ],
    "Forex": [
        r"metatrader|tradingview",
        r"\beur/?usd\b|gbp/?jpy\b|xau/?usd\b|btc/?usd\b",
        r"\b[mh]\d{1,2}\b\s*(?:timeframe)?",  # M1 M5 H1 H4 D1
        r"\bpip(s)?\b|\bleverage\b|\btake\s*profit\b|\bstop\s*loss\b",
    ],
    "Conversations": [
        r"whatsapp|telegram|messenger|imessage|signal",
        r"\b(en ligne|online|vu a|seen at)\b",
    ],
    "Receipts": [
        r"\btva\b|\bttc\b|\bht\b",
        r"recu|ticket de caisse",
        r"\btotal\b.*\d+[.,]\d{2}",
    ],
    "Invoices": [
        r"\bfacture\b|\binvoice\b|\bbill to\b|\bfacturer a\b",
        r"\bn[°o]\s*facture\b|\binvoice\s*(no|number|#)\b",
        r"\bmontant\s+(total|du|a payer)\b",
        r"\bdate\s+d[''']?[eé]ch[eé]ance\b|\bdue date\b",
    ],
    "CV": [
        r"\bcurriculum vitae\b|\bresume\b|\bcv\b",
        r"\bexp[eé]rience\s+professionnelle\b|\bwork experience\b",
        r"\bformation\b|\beducation\b|\bdiplom[eé]\b",
        r"\bcomp[eé]tences\b|\bskills\b",
    ],
    "Contracts": [
        r"\bcontrat\b|\bcontract\b|\bagreement\b|\baccord\b",
        r"\bclause\b|\bparties\b|\bsignataire\b",
        r"\bconditions g[eé]n[eé]rales\b|\bterms and conditions\b",
        r"\bdur[eé]e du contrat\b|\bterm of (the )?agreement\b",
    ],
    "Reports": [
        r"\brapport\b|\breport\b",
        r"\bsommaire\b|\btable des mati[eè]res\b|\btable of contents\b",
        r"\bconclusion\b|\bsynthese\b|\bexecutive summary\b",
    ],
}


# Categorie par defaut selon le type de fichier (utilise si aucun keyword match)
DEFAULT_CATEGORY_BY_KIND = {
    "xlsx": "Spreadsheets",
    "pdf": "Other",
    "docx": "Other",
    "image": "Other",
}


# ---------------------------------------------------------------------------
# Heuristiques images sans OCR : nom de fichier + EXIF + dimensions
# ---------------------------------------------------------------------------
# Patterns nom de fichier -> categorie + sous-dossier
FILENAME_RULES = [
    (re.compile(r"^screen[\s\-_]?shot", re.IGNORECASE), "Screenshots", "Screenshots"),
    (re.compile(r"^capture[\s\-_]", re.IGNORECASE), "Screenshots", "Screenshots"),
    (re.compile(r"^screenshot", re.IGNORECASE), "Screenshots", "Screenshots"),
    (re.compile(r"^whatsapp\s*image", re.IGNORECASE), "WhatsApp", "WhatsApp"),
    (re.compile(r"^wa\d+\.jpe?g$", re.IGNORECASE), "WhatsApp", "WhatsApp"),
    (re.compile(r"^snapchat[\s\-_]", re.IGNORECASE), "Snapchat", "Snapchat"),
    (re.compile(r"^img[_\-]\d{4}", re.IGNORECASE), "Photos", "Photos"),
    (re.compile(r"^dsc[fn]?\d{3,}", re.IGNORECASE), "Photos", "Photos"),
    (re.compile(r"^pxl[_\-]\d{8}", re.IGNORECASE), "Photos", "Photos"),
    (re.compile(r"^vlcsnap[\s\-_]", re.IGNORECASE), "VideoFrames", "VideoFrames"),
    (re.compile(r"^facebook[\s\-_]", re.IGNORECASE), "Facebook", "Facebook"),
    (re.compile(r"^insta(gram)?[\s\-_]", re.IGNORECASE), "Instagram", "Instagram"),
    (re.compile(r"^meme[\s\-_]", re.IGNORECASE), "Memes", "Memes"),
]


def _get_exif_year(path: Path) -> Optional[int]:
    """Retourne l'annee dans EXIF DateTimeOriginal, ou None."""
    try:
        with Image.open(path) as img:
            exif = img.getexif()
            if not exif:
                return None
            # 36867 = DateTimeOriginal, 306 = DateTime
            for tag in (36867, 306):
                val = exif.get(tag)
                if isinstance(val, str) and len(val) >= 4:
                    try:
                        year = int(val[:4])
                        if 1990 <= year <= 2100:
                            return year
                    except ValueError:
                        continue
    except (OSError, AttributeError, Exception):  # noqa: BLE001
        pass
    return None


def _is_likely_screenshot_by_dims(path: Path) -> bool:
    """Heuristique simple : dimensions typiques d'un screenshot smartphone/desktop.
    - Portrait haute resolution mais ratio strict de telephone (ex: 1080x1920, 1170x2532)
    - Paysage exactement aux dims de l'ecran (1920x1080, 2560x1440, 2880x1800)
    """
    try:
        with Image.open(path) as img:
            w, h = img.size
    except (OSError, Exception):  # noqa: BLE001
        return False
    common_phone = {(1080, 1920), (1080, 2340), (1170, 2532), (1284, 2778), (1440, 2960)}
    common_desktop = {(1920, 1080), (2560, 1440), (2880, 1800), (3840, 2160), (3440, 1440)}
    return (w, h) in common_phone or (h, w) in common_phone \
        or (w, h) in common_desktop or (h, w) in common_desktop


# ---------------------------------------------------------------------------
# Match contre les dossiers deja utilises par l'utilisateur
# ---------------------------------------------------------------------------
def _strip_accents_lower(s: str) -> str:
    """Lowercase + retire accents. Preserve les espaces et la ponctuation."""
    if not s:
        return ""
    nfkd = unicodedata.normalize("NFKD", s)
    no_accent = "".join(c for c in nfkd if not unicodedata.combining(c))
    return no_accent.lower()


def _normalize_compact(s: str) -> str:
    """Compact : pas d'espaces ni ponctuation. Pour matcher 'Sky Vision' ~= 'skyvision'."""
    return re.sub(r"[^a-z0-9]+", "", _strip_accents_lower(s))


def _tokenize(s: str, min_len: int = 3) -> list[str]:
    """Split en mots alphanumeriques en ignorant accents/casse/ponctuation."""
    cleaned = _strip_accents_lower(s)
    return [tok for tok in re.split(r"[^a-z0-9]+", cleaned) if len(tok) >= min_len]


def _fuzzy_in(needle: str, haystack_tokens: list[str], threshold: float = 0.85) -> bool:
    """Retourne True si `needle` est present (exact ou fuzzy) dans la liste de tokens."""
    if not needle:
        return False
    for tok in haystack_tokens:
        if needle == tok:
            return True
        # Fuzzy : on n'evalue que si les longueurs sont comparables (evite faux positifs)
        if abs(len(tok) - len(needle)) <= 2 and len(needle) >= 4:
            ratio = SequenceMatcher(None, needle, tok).ratio()
            if ratio >= threshold:
                return True
    return False


def _bigrams(tokens: list[str]) -> list[str]:
    """Genere les paires de tokens adjacents concatenees.
    Permet de matcher 'skyvision' (1 mot dans le dossier) contre 'Sky Vision'
    (2 mots dans le texte) : tokens=['sky','vision'] -> bigrams=['skyvision']."""
    return [a + b for a, b in zip(tokens, tokens[1:])]


def match_known_folder(
    text: str,
    filename: str,
    known_folders: list[tuple[str, int]],
    min_token_len: int = 4,
) -> Optional[tuple[str, float]]:
    """Cherche un dossier deja utilise dont le nom (ou un de ses tokens)
    apparait dans le texte OCR ou le nom de fichier.

    Strategie en 3 niveaux par dossier candidat :
      1. Match compact : 'skyvision' presente en sous-chaine dans le texte
         normalise sans espaces (gere 'Sky Vision', 'sky-vision', 'SkyVision')
      2. Match tokens : chaque mot du dossier (>= 4 chars) est present
         (exact ou fuzzy) dans le texte. Confidence selon le ratio matches.
      3. Match fuzzy : si l'OCR a mal lu (ex: 'Vsion'), on tolere 1-2 typos
         par mot via SequenceMatcher.

    Retourne (folder, confidence) ou None. Confidence entre 0.55 et 0.95.
    """
    if not known_folders:
        return None

    text_norm_compact = _normalize_compact(text)
    name_norm_compact = _normalize_compact(filename)
    text_tokens = _tokenize(text, min_len=3)
    name_tokens = _tokenize(filename, min_len=3)
    all_tokens = text_tokens + name_tokens
    # Bigrammes : 'Sky Vision' -> 'skyvision' pour matcher dossier compact
    all_tokens_extended = all_tokens + _bigrams(text_tokens) + _bigrams(name_tokens)

    best: Optional[tuple[str, float]] = None

    for folder, used_count in known_folders:
        # Segments du chemin (Bank/Boursorama -> 2 segments)
        segments = [s for s in folder.replace("\\", "/").split("/") if s]
        for seg in segments:
            seg_compact = _normalize_compact(seg)
            if len(seg_compact) < min_token_len:
                continue

            # === Niveau 1 : match compact (sous-chaine sans espaces) ===
            in_text_compact = seg_compact in text_norm_compact
            in_name_compact = seg_compact in name_norm_compact
            if in_text_compact or in_name_compact:
                conf = 0.80
                if used_count >= 3:
                    conf += 0.05
                if in_text_compact and in_name_compact:
                    conf += 0.10
                return (folder, min(conf, 0.95))

            # === Niveau 2 : match tokens du dossier (vs tokens + bigrams) ===
            seg_tokens = _tokenize(seg, min_len=min_token_len)
            if not seg_tokens:
                # Dossier d'1 seul gros token (ex: 'skyvision') : on teste
                # directement contre tokens + bigrams du texte
                if len(seg_compact) >= min_token_len:
                    if _fuzzy_in(seg_compact, all_tokens_extended):
                        conf = 0.75
                        if used_count >= 3:
                            conf += 0.05
                        if (best is None) or (conf > best[1]):
                            best = (folder, conf)
                continue
            n_match = sum(1 for t in seg_tokens if _fuzzy_in(t, all_tokens_extended))
            ratio = n_match / len(seg_tokens)
            if ratio >= 1.0:
                # Tous les tokens matchent (fuzzy ou exact)
                conf = 0.75
                if used_count >= 3:
                    conf += 0.05
                if (best is None) or (conf > best[1]):
                    best = (folder, conf)
            elif ratio >= 0.6 and len(seg_tokens) >= 2:
                # Majorite (mais pas tous) -> match faible
                conf = 0.55 + 0.1 * ratio
                if (best is None) or (conf > best[1]):
                    best = (folder, conf)

    return best


def heuristic_image_category(path: Path) -> Optional[tuple[str, str, float]]:
    """Tente une categorisation d'image SANS OCR : nom de fichier, dimensions,
    EXIF. Retourne (category, suggested_folder, confidence) ou None."""
    name = path.name
    for rx, cat, folder in FILENAME_RULES:
        if rx.search(name):
            # Si EXIF dispo et c'est une photo, ajoute l'annee
            if cat == "Photos":
                year = _get_exif_year(path)
                if year:
                    return (cat, f"{folder}/{year}", 0.85)
            return (cat, folder, 0.75)

    # Pas de match filename : on tente les dimensions screenshot
    if _is_likely_screenshot_by_dims(path):
        return ("Screenshots", "Screenshots", 0.60)

    # Photo avec EXIF year mais nom non-standard
    year = _get_exif_year(path)
    if year:
        return ("Photos", f"Photos/{year}", 0.55)

    return None


# ---------------------------------------------------------------------------
# Dataclass de retour
# ---------------------------------------------------------------------------
@dataclass
class SortSuggestion:
    category: str
    suggested_folder: str
    confidence: float  # 0.0 a 1.0
    reason: str  # "chart_heuristic" | "keyword:Bank" | "learned_rule" | "fallback"


# ---------------------------------------------------------------------------
# Voie 1 : detection visuelle d'un chart de trading
# ---------------------------------------------------------------------------
def detect_chart_trading(path: Path) -> bool:
    """Heuristique pixels : > 5% rouge + > 5% vert + fond sombre dominant
    + presence de lignes droites verticales (chandelles + grille).
    """
    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            # Reduce pour vitesse, l'heuristique survit au resize
            img.thumbnail((256, 256))
            arr = np.asarray(img, dtype=np.uint8)
    except (OSError, Image.UnidentifiedImageError):
        return False

    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    total = arr.shape[0] * arr.shape[1]

    # Pixels rouges (chandelles down) : R > G + 30 et R > B + 30
    red_mask = (r > g.astype(int) + 30) & (r > b.astype(int) + 30)
    red_ratio = red_mask.sum() / total

    # Pixels verts (chandelles up)
    green_mask = (g > r.astype(int) + 30) & (g > b.astype(int) + 30)
    green_ratio = green_mask.sum() / total

    # Fond sombre dominant : luminance < 30/255 sur > 60% des pixels
    luminance = (0.299 * r + 0.587 * g + 0.114 * b).astype(np.uint8)
    dark_ratio = (luminance < 30).sum() / total

    has_red = red_ratio > 0.05
    has_green = green_ratio > 0.05
    is_dark = dark_ratio > 0.40  # un peu plus permissif que 60% pour marges

    return has_red and has_green and is_dark


# ---------------------------------------------------------------------------
# Voie 2 : OCR + keywords (STUB)
# ---------------------------------------------------------------------------
def ocr_text(path: Path) -> str:
    """OCR on-device via pytesseract. Retourne "" si Tesseract n'est pas
    installe (l'app continue de fonctionner, juste la classification par
    mots-cles est desactivee).

    Pour activer l'OCR sur Windows : installer Tesseract
        winget install --id UB-Mannheim.TesseractOCR
        (ou bin direct : https://github.com/UB-Mannheim/tesseract/wiki)
    Tesseract doit etre dans le PATH OU on peut pointer le binary :
        pytesseract.pytesseract.tesseract_cmd = r"C:\\...\\tesseract.exe"

    Cette fonction cache le resultat de la verification de disponibilite
    pour eviter de retomber dessus a chaque appel.
    """
    if not _ocr_available():
        return ""
    try:
        import pytesseract  # type: ignore[import-not-found]
        with Image.open(path) as img:
            # fra+eng : Tesseract gere multi-langues si les data files sont
            # presents. Tous les builds Windows recents incluent les deux.
            try:
                return pytesseract.image_to_string(img, lang="fra+eng")
            except pytesseract.TesseractError:
                # Fallback eng seul si fra non installe
                return pytesseract.image_to_string(img, lang="eng")
    except Exception:  # noqa: BLE001 — on degrade gracefully
        return ""


_ocr_check_done = False
_ocr_ok = False


# Chemins standards ou Tesseract peut etre installe sur Windows si le PATH
# n'est pas configure (winget install ne met pas toujours dans le PATH).
_TESSERACT_CANDIDATES = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    str(Path.home() / "AppData" / "Local" / "Programs" / "Tesseract-OCR" / "tesseract.exe"),
    str(Path.home() / "AppData" / "Local" / "Tesseract-OCR" / "tesseract.exe"),
]


def _find_tesseract_binary() -> Optional[str]:
    """Cherche tesseract.exe : d'abord via le PATH, puis chemins standards."""
    import shutil
    if found := shutil.which("tesseract"):
        return found
    for candidate in _TESSERACT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    return None


def _ocr_available() -> bool:
    """Verifie une seule fois si pytesseract+Tesseract sont utilisables.
    Configure pytesseract.tesseract_cmd si le binaire est trouve hors-PATH."""
    global _ocr_check_done, _ocr_ok
    if _ocr_check_done:
        return _ocr_ok
    _ocr_check_done = True
    try:
        import pytesseract  # type: ignore[import-not-found]
        binary = _find_tesseract_binary()
        if binary:
            pytesseract.pytesseract.tesseract_cmd = binary
        # get_tesseract_version leve TesseractNotFoundError si binaire absent
        pytesseract.get_tesseract_version()
        _ocr_ok = True
    except Exception:  # noqa: BLE001
        _ocr_ok = False
    return _ocr_ok


def detect_text_keywords(text: str) -> Optional[str]:
    """Cherche un match dans les KEYWORD_RULES. Retourne la categorie ou None."""
    if not text:
        return None
    t = text.lower()
    matches: Counter[str] = Counter()
    for category, patterns in KEYWORD_RULES.items():
        for pat in patterns:
            if re.search(pat, t, flags=re.IGNORECASE):
                matches[category] += 1
    if not matches:
        return None
    return matches.most_common(1)[0][0]


# ---------------------------------------------------------------------------
# Persistance des regles apprises et des dossiers utilises
# ---------------------------------------------------------------------------
def _data_path(name: str) -> Path:
    base = Path.home() / ".organisateur-pc"
    base.mkdir(parents=True, exist_ok=True)
    return base / name


def load_known_folders() -> list[tuple[str, int]]:
    """Liste les noms de dossiers deja utilises avec leur frequence,
    triee par usage decroissant pour les suggestions UX."""
    p = _data_path("sort_folders.json")
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return []
        return sorted(data.items(), key=lambda kv: -kv[1])
    except (OSError, json.JSONDecodeError):
        return []


def remember_folder(folder: str) -> None:
    """Increment le compteur d'usage d'un nom de dossier. A appeler
    chaque fois que l'utilisateur valide un classement."""
    p = _data_path("sort_folders.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data[folder] = int(data.get(folder, 0)) + 1
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def load_learned_rules() -> dict[str, str]:
    """pattern -> dossier. Le pattern est une signature simple (pour V1
    : la categorie auto-detectee). On enrichira avec des hashes ou des
    mots-cles specifiques quand on aura des retours d'usage."""
    p = _data_path("sort_rules.json")
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def remember_rule(pattern: str, folder: str) -> None:
    p = _data_path("sort_rules.json")
    try:
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data[pattern] = folder
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Pipeline principal de classement
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Pipeline semantique via embeddings (CLIP + E5)
# ---------------------------------------------------------------------------
# Seuils calibres a partir des distributions observees. Calibrables.
# Avec le max-of-K (vs centroide seul), les scores sont plus eleves -> seuils
# legerement augmentes mais on capture plus de matches faibles aussi.
SEMANTIC_STRONG_MIN = 0.45  # score absolu minimum pour considerer un match
SEMANTIC_STRONG_DELTA = 0.02  # ecart minimum entre top1 et top2
SEMANTIC_VERY_STRONG = 0.70  # au-dessus, on est tres confiant
SEMANTIC_WEAK_MIN = 0.35  # tolere une suggestion meme faible (vs fallback Other)


_seeded_folders: set[str] = set()
_seed_lock = __import__("threading").Lock()


def _ensure_text_seeded(known_folders: list[tuple[str, int]]) -> None:
    """DESACTIVE par defaut. Seeder le NOM du dossier comme exemplar texte
    s'est avere etre du bruit pur pour les noms propres (genre 'tomntoms',
    'Sejong'), creant des matches au hasard sur des images abstraites.

    L'utilisateur doit explicitement amorcer un dossier via 'Apprentissage...'
    pour qu'il soit propose par le pipeline semantique.
    """
    return  # no-op intentionnel


_purged_text_seeds = False


def _semantic_match(
    path: Path,
    text: str,
    kind: str,
) -> Optional[tuple[str, float, str]]:
    """Calcule un match semantique via CLIP (image) + E5 (texte).
    Retourne (folder, confidence, reason) ou None si pas de match fiable.

    Honnete : on ne propose un dossier QUE si l'user y a explicitement amorce
    des exemples reels (pas le seeding bidon du nom de dossier).
    """
    if not _emb.embeddings_available():
        return None
    try:
        from . import exemplars as _ex
        store = _ex.ExemplarStore.get()
    except Exception:  # noqa: BLE001
        return None
    # Au premier appel, nettoie les anciens seeds texte qui creaient du bruit
    global _purged_text_seeds
    if not _purged_text_seeds:
        try:
            store.purge_text_only_seeds()
        except Exception:  # noqa: BLE001
            pass
        _purged_text_seeds = True
    if not store.known_folders():
        return None

    img_path = path if kind == "image" else None
    txt = text if (text and len(text.strip()) >= 5) else None

    matches = store.best_match_combined(img_path, txt, top_n=5)
    if not matches:
        return None
    top_folder, top_score = matches[0]
    second_score = matches[1][1] if len(matches) > 1 else -1.0

    # Niveau 1 : tres fort match -> 95% conf
    if top_score >= SEMANTIC_VERY_STRONG:
        return (top_folder, min(0.95, 0.80 + top_score * 0.15), "semantic_strong")

    # Niveau 2 : score correct + delta net avec le 2e -> 80% conf
    if top_score >= SEMANTIC_STRONG_MIN and (top_score - second_score) >= SEMANTIC_STRONG_DELTA:
        conf = 0.65 + (top_score - SEMANTIC_STRONG_MIN) * 0.5 + (top_score - second_score) * 0.3
        return (top_folder, min(0.85, conf), "semantic_match")

    # Niveau 3 : match faible -> seulement si delta net (sinon c'est du wild guess)
    if top_score >= SEMANTIC_WEAK_MIN and (top_score - second_score) >= 0.05:
        conf = 0.40 + (top_score - SEMANTIC_WEAK_MIN) * 0.5
        return (top_folder, min(0.55, conf), "semantic_weak")

    return None


def propose_folder(path: Path) -> SortSuggestion:
    """Retourne une suggestion de classement.

    Ordre de priorite :
      1. Match SEMANTIQUE (CLIP image + E5 texte) contre les exemplars
         des dossiers existants. C'est le signal le plus fort si dispo.
      2. Match contre dossier deja utilise (fuzzy regex sur nom)
      3. Keywords categories (Bank, Forex, Invoices, CV...)
      4. Chart trading visuel (images)
      5. Heuristiques nom de fichier / EXIF / dimensions
      6. Fallback Other
    """
    rules = load_learned_rules()
    known_folders = load_known_folders()
    kind = docs.kind_of(path)

    # Seed les centroides texte avec les noms de dossiers connus (une fois)
    _ensure_text_seeded(known_folders)

    # Extrait le texte selon le type (OCR pour images, lib pour docs)
    if kind in ("pdf", "docx", "xlsx"):
        text = docs.extract_text(path, max_chars=20_000) or ""
    elif kind == "image":
        text = ocr_text(path)
    else:
        text = ""

    # === Priorite haute : match fuzzy NOM DE DOSSIER (signal tres fiable) ===
    # Match exact d'un nom de dossier connu dans OCR/nom = signal tres fort
    # (ex: image contient "SKY VISION" -> dossier "skyvision"). On l'utilise
    # SAUF si le semantique est tres fort (semantic_strong = match visuel direct
    # sur un autre dossier avec beaucoup d'exemplars correspondants).
    fuzzy = match_known_folder(text, path.name, known_folders)
    sem = _semantic_match(path, text, kind)

    # Fuzzy fort (>=0.85 = match compact direct) bat sem sauf semantic_strong (>=0.93)
    if fuzzy and fuzzy[1] >= 0.85:
        if sem is None or sem[1] < 0.93:
            folder, conf = fuzzy
            cat = folder.split("/")[0].split("\\")[0] or "Custom"
            return SortSuggestion(
                category=cat,
                suggested_folder=folder,
                confidence=conf,
                reason="match_known_folder",
            )

    # === Priorite : match semantique ===
    if sem is not None:
        folder, conf, why = sem
        cat = folder.split("/")[0].split("\\")[0] or "Custom"
        return SortSuggestion(
            category=cat,
            suggested_folder=folder,
            confidence=conf,
            reason=why,
        )

    # === Fuzzy match plus faible (> keywords mais < semantic) ===
    if fuzzy:
        folder, conf = fuzzy
        cat = folder.split("/")[0].split("\\")[0] or "Custom"
        return SortSuggestion(
            category=cat,
            suggested_folder=folder,
            confidence=conf,
            reason="match_known_folder",
        )

    # === Priorite 2 : keywords categories generiques ===
    if cat := detect_text_keywords(text):
        signature = f"keyword:{cat}"
        if learned := rules.get(signature):
            return SortSuggestion(
                category=cat,
                suggested_folder=learned,
                confidence=0.85,
                reason="learned_rule",
            )
        # Pour les images, confiance plus basse (OCR moins fiable)
        conf = 0.75 if kind != "image" else 0.65
        return SortSuggestion(
            category=cat,
            suggested_folder=cat,
            confidence=conf,
            reason=f"keyword:{cat}",
        )

    # === Priorite 3 : chart trading (images uniquement) ===
    if kind == "image" and detect_chart_trading(path):
        signature = "chart_trading"
        if learned := rules.get(signature):
            return SortSuggestion(
                category="Forex",
                suggested_folder=learned,
                confidence=0.95,
                reason="learned_rule",
            )
        return SortSuggestion(
            category="Forex",
            suggested_folder="Forex/Charts",
            confidence=0.85,
            reason="chart_heuristic",
        )

    # === Priorite 4 : heuristiques nom de fichier / EXIF / dimensions (images) ===
    if kind == "image":
        if h := heuristic_image_category(path):
            cat, folder, conf = h
            signature = f"heur:{cat}"
            if learned := rules.get(signature):
                return SortSuggestion(
                    category=cat,
                    suggested_folder=learned,
                    confidence=conf + 0.10,
                    reason="learned_rule",
                )
            return SortSuggestion(
                category=cat,
                suggested_folder=folder,
                confidence=conf,
                reason=f"heuristic:{cat}",
            )

    # === Priorite 5 : categorie par defaut selon le type ===
    if kind in ("pdf", "docx", "xlsx"):
        default_cat = DEFAULT_CATEGORY_BY_KIND.get(kind, "Other")
        return SortSuggestion(
            category=default_cat,
            suggested_folder=default_cat,
            confidence=0.25,
            reason=f"type:{kind}",
        )

    # Fallback final
    return SortSuggestion(
        category="Other",
        suggested_folder="Other",
        confidence=0.0,
        reason="fallback",
    )

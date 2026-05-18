"""Palette de couleurs et stylesheet QSS de l'app. Inspire de l'app
Android pour la coherence visuelle (mode dark, accents violet/turquoise)."""

# Palette (hex)
BG = "#0f1117"
CARD = "#1a1d27"
CARD2 = "#252836"
BORDER = "#2e3244"
TEXT = "#e4e6f0"
TEXT2 = "#8b8fa3"
TEXT3 = "#5a5e70"
ACCENT = "#6c5ce7"  # violet (cote dedup)
ACCENT2 = "#a29bfe"
TURQUOISE = "#00b894"  # cote tri (pour distinguer)
DANGER = "#ff6b6b"
WARN = "#ffd43b"
OK = "#51cf66"


# Couleurs de badges par categorie. Hex + couleur texte (claire/sombre).
# Toute categorie inconnue tombe sur DEFAULT.
CATEGORY_COLORS: dict[str, tuple[str, str]] = {
    # categories docs typiques (mockup)
    "Factures":      ("#4f9eff", "white"),  # bleu
    "Invoices":      ("#4f9eff", "white"),
    "Contrats":      ("#a78bfa", "white"),  # violet clair
    "Contracts":     ("#a78bfa", "white"),
    "Devis":         ("#f97316", "white"),  # orange
    "Administratif": ("#22c55e", "white"),  # vert
    "Reports":       ("#0ea5e9", "white"),  # cyan
    "CV":            ("#eab308", "black"),  # jaune
    # categories images existantes
    "Images produit":("#a78bfa", "white"),
    "Photos":        ("#06b6d4", "white"),
    "Screenshots":   ("#64748b", "white"),
    "WhatsApp":      ("#22c55e", "white"),
    "Snapchat":      ("#facc15", "black"),
    "Facebook":      ("#1d4ed8", "white"),
    "Instagram":     ("#ec4899", "white"),
    "Memes":         ("#f43f5e", "white"),
    "VideoFrames":   ("#475569", "white"),
    # categories metier
    "Bank":          ("#10b981", "white"),
    "Forex":         ("#7c3aed", "white"),
    "Conversations": ("#22d3ee", "black"),
    "Receipts":      ("#fb923c", "white"),
    "Spreadsheets":  ("#16a34a", "white"),
    # fallback
    "Other":         ("#475569", "white"),
    "Custom":        ("#6c5ce7", "white"),
}


def category_color(category: str) -> tuple[str, str]:
    """Retourne (bg, fg) pour le badge d'une categorie. Fallback Custom."""
    if category in CATEGORY_COLORS:
        return CATEGORY_COLORS[category]
    # Match insensible a la casse / prefixe
    for k, v in CATEGORY_COLORS.items():
        if k.lower() == category.lower():
            return v
    # Premier segment d'un chemin (Bank/Boursorama -> Bank)
    first = category.split("/")[0].split("\\")[0]
    if first in CATEGORY_COLORS:
        return CATEGORY_COLORS[first]
    return CATEGORY_COLORS["Custom"]


QSS = f"""
QMainWindow, QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}}

QTabWidget::pane {{
    border: 1px solid {BORDER};
    background: {BG};
    top: -1px;
}}
QTabBar::tab {{
    background: {CARD};
    color: {TEXT2};
    padding: 8px 18px;
    border: 1px solid {BORDER};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}
QTabBar::tab:selected {{
    background: {BG};
    color: {TEXT};
    border-bottom: 1px solid {BG};
}}

QPushButton {{
    background: {ACCENT};
    color: white;
    border: none;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {ACCENT2};
    color: black;
}}
QPushButton:disabled {{
    background: {CARD2};
    color: {TEXT3};
}}
QPushButton[role="secondary"] {{
    background: {CARD2};
    color: {TEXT};
    border: 1px solid {BORDER};
}}
QPushButton[role="danger"] {{
    background: {DANGER};
    color: white;
}}

QLineEdit, QTextEdit {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 8px;
}}

QListWidget, QTreeView, QTableView {{
    background: {CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px;
}}
QListWidget::item:selected,
QTreeView::item:selected,
QTableView::item:selected {{
    background: {ACCENT};
    color: white;
}}

QProgressBar {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 4px;
    text-align: center;
    color: {TEXT};
    height: 18px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 3px;
}}

QCheckBox {{
    color: {TEXT};
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1.5px solid {BORDER};
    border-radius: 3px;
    background: {CARD};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}

QLabel[role="title"] {{
    font-size: 18px;
    font-weight: 700;
    color: {TEXT};
}}
QLabel[role="subtitle"] {{
    color: {TEXT2};
    font-size: 12px;
}}
QLabel[role="badge_exact"] {{
    background: {ACCENT};
    color: white;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 10px;
}}
QLabel[role="badge_quasi"] {{
    background: {WARN};
    color: black;
    padding: 2px 8px;
    border-radius: 4px;
    font-weight: 700;
    font-size: 10px;
}}

QScrollBar:vertical {{
    background: {BG};
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {TEXT3};
}}
"""


def fmt_size(bytes_: int) -> str:
    if bytes_ < 1024:
        return f"{bytes_} o"
    if bytes_ < 1024 * 1024:
        return f"{bytes_ / 1024:.1f} Ko"
    if bytes_ < 1024 * 1024 * 1024:
        return f"{bytes_ / 1024 / 1024:.1f} Mo"
    return f"{bytes_ / 1024 / 1024 / 1024:.2f} Go"

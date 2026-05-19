"""Panneau de visualisation reutilisable.

Affiche l'apercu d'un fichier (image ou document) :
  - Image -> QLabel + QPixmap rescale
  - PDF / DOCX / XLSX -> QTextEdit read-only avec le texte extrait
  - Comparaison cote-a-cote pour les quasi-doublons (jusqu'a 4 images)

Pour les images, la thumbnail est generee a la volee via Pillow puis
convertie en QImage / QPixmap (evite de garder le fichier entier en RAM).
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from PIL import Image
from PIL.ImageQt import ImageQt
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QStackedWidget, QSizePolicy, QFrame,
)

from core import docs
from .styles import fmt_size


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
# Limites pour eviter les segfaults / OOM lors du chargement des thumbnails
_THUMB_MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25 Mo : au-dela, on ne charge pas
# Extensions qu'on peut decoder NATIVEMENT via Qt (plus stable que Pillow,
# car pas d'allocation ImageQt / conversion Pillow->Qt qui peut segfaulter).
_QT_NATIVE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif"}
# Extensions qu'on ne tente meme pas (HEIC necessite pillow-heif qui peut
# planter sur certains fichiers ; on prefere afficher pas-de-vignette plutot
# qu'un crash).
_THUMB_SKIP_EXTS = {".heic", ".heif"}


def load_thumbnail(path: Path, max_size: tuple[int, int] = (1024, 1024)) -> Optional[QPixmap]:
    """Charge une image et rend un QPixmap. Robuste aux fichiers corrompus.

    Strategie :
      1. Verifie la taille du fichier ; au-dela de 25 Mo, on skip (risque OOM
         et le rendu serait scale a 96x96 de toute facon).
      2. Pour les formats natifs Qt (jpg/png/bmp/gif), utilise QImageReader
         qui est plus stable que Pillow + ImageQt (moins de risques de
         segfault au niveau C).
      3. Fallback Pillow pour les formats moins courants (webp, tiff).
      4. HEIC : skip pur et simple (pas de codec stable embarque).
      5. Toute exception (y compris MemoryError) -> None, pas de crash.

    max_size sert de plafond pour ne pas exploser la RAM.
    """
    # Filtre 1 : taille du fichier
    try:
        if path.stat().st_size > _THUMB_MAX_FILE_SIZE_BYTES:
            return None
    except OSError:
        return None

    suffix = path.suffix.lower()

    # Filtre 2 : extensions a ne pas tenter
    if suffix in _THUMB_SKIP_EXTS:
        return None

    # Voie rapide : decodeur natif Qt (stable, pas de Pillow)
    if suffix in _QT_NATIVE_EXTS:
        try:
            from PyQt6.QtCore import QSize
            from PyQt6.QtGui import QImageReader
            reader = QImageReader(str(path))
            # Demande a Qt de pre-scale au chargement (gros gain de RAM
            # pour les grosses photos)
            reader.setScaledSize(QSize(max_size[0], max_size[1]))
            reader.setAutoTransform(True)  # respecte EXIF orientation
            img = reader.read()
            if not img.isNull():
                return QPixmap.fromImage(img)
        except Exception:  # noqa: BLE001
            pass  # bascule sur Pillow

    # Voie lente : Pillow (webp, tiff, png anime, etc.)
    try:
        with Image.open(path) as img:
            img = img.convert("RGBA")
            img.thumbnail(max_size, Image.Resampling.LANCZOS)
            qimg = ImageQt(img).copy()  # copy pour eviter le GC Pillow
        return QPixmap.fromImage(qimg)
    except (Exception, MemoryError):  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Cellule = 1 fichier (utilise seul ou en grille)
# ---------------------------------------------------------------------------
class _PreviewCell(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self.title = QLabel("(rien a afficher)")
        self.title.setProperty("role", "title")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)

        self.meta = QLabel("")
        self.meta.setProperty("role", "subtitle")
        self.meta.setWordWrap(True)
        layout.addWidget(self.meta)

        # Stacked : image OU texte
        self.stack = QStackedWidget()

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(240, 240)
        self.image_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.stack.addWidget(self.image_label)

        self.text_view = QTextEdit()
        self.text_view.setReadOnly(True)
        self.stack.addWidget(self.text_view)

        self.empty_label = QLabel("Aucun apercu disponible")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setProperty("role", "subtitle")
        self.stack.addWidget(self.empty_label)

        layout.addWidget(self.stack, stretch=1)

        # Bouton ouvrir
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.open_btn = QPushButton("Ouvrir avec l'app par defaut")
        self.open_btn.setProperty("role", "secondary")
        self.open_btn.clicked.connect(self._open_external)
        self.open_btn.setEnabled(False)
        btn_row.addWidget(self.open_btn)
        layout.addLayout(btn_row)

        self._current_path: Optional[Path] = None
        self._source_pixmap: Optional[QPixmap] = None  # cache du pixmap original

    def show_path(self, path: Path) -> None:
        self._current_path = path
        self._source_pixmap = None
        kind = docs.kind_of(path)
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        self.title.setText(path.name)
        self.meta.setText(f"{kind.upper()}  ·  {fmt_size(size)}  ·  {path.parent}")
        self.open_btn.setEnabled(True)

        if kind == "image":
            pm = load_thumbnail(path)
            if pm is None:
                self.stack.setCurrentWidget(self.empty_label)
                return
            self._source_pixmap = pm
            self._rescale_current()
            self.stack.setCurrentWidget(self.image_label)
            return

        if kind in ("pdf", "docx", "xlsx"):
            text = docs.extract_text(path, max_chars=10_000)
            if not text:
                self.text_view.setPlainText(
                    "(Aucun texte extrait — fichier vide, chiffre, ou lib absente)"
                )
            else:
                self.text_view.setPlainText(text)
            self.stack.setCurrentWidget(self.text_view)
            return

        self.stack.setCurrentWidget(self.empty_label)

    def show_empty(self, msg: str = "Selectionne un fichier pour le visualiser") -> None:
        self._current_path = None
        self._source_pixmap = None
        self.title.setText("Apercu")
        self.meta.setText("")
        self.empty_label.setText(msg)
        self.stack.setCurrentWidget(self.empty_label)
        self.open_btn.setEnabled(False)

    def _rescale_current(self) -> None:
        """Rescale le pixmap source pour qu'il rentre dans image_label."""
        if self._source_pixmap is None:
            return
        target = self.image_label.size()
        if target.width() <= 0 or target.height() <= 0:
            self.image_label.setPixmap(self._source_pixmap)
            return
        scaled = self._source_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_label.setPixmap(scaled)

    def resizeEvent(self, event):  # noqa: N802 (Qt API)
        super().resizeEvent(event)
        if self._source_pixmap is not None:
            self._rescale_current()

    def _open_external(self) -> None:
        if self._current_path is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._current_path)))


# ---------------------------------------------------------------------------
# Panneau public — affiche 1 ou plusieurs fichiers en grille
# ---------------------------------------------------------------------------
class PreviewPanel(QWidget):
    """Panneau d'apercu.

    - set_path(p)        : un seul fichier
    - set_paths([p1,p2]) : grille de 2 a 4 (utile pour comparer quasi-doublons)
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._main = QVBoxLayout(self)
        self._main.setContentsMargins(0, 0, 0, 0)
        self._main.setSpacing(0)
        self._cell = _PreviewCell(self)
        self._main.addWidget(self._cell)
        # Container pour la grille (mode multi)
        self._grid_container: Optional[QWidget] = None
        self._cells: list[_PreviewCell] = [self._cell]

        self._cell.show_empty()

    def set_path(self, path: Path) -> None:
        self._ensure_single()
        self._cells[0].show_path(path)

    def set_paths(self, paths: list[Path]) -> None:
        if not paths:
            self._ensure_single()
            self._cells[0].show_empty()
            return
        if len(paths) == 1:
            self.set_path(paths[0])
            return
        # Grille (max 4)
        paths = paths[:4]
        self._build_grid(len(paths))
        for cell, p in zip(self._cells, paths):
            cell.show_path(p)

    def clear(self) -> None:
        self._ensure_single()
        self._cells[0].show_empty()

    # -----------------------------------------------------------------
    def _clear_all(self) -> None:
        """Detruit toutes les cells et l'eventuel grid_container, en les
        retirant proprement du layout principal d'abord."""
        if self._grid_container is not None:
            self._main.removeWidget(self._grid_container)
            self._grid_container.deleteLater()
            self._grid_container = None
        for c in self._cells:
            self._main.removeWidget(c)
            c.deleteLater()
        self._cells = []
        self._cell = None  # type: ignore[assignment]

    def _ensure_single(self) -> None:
        if len(self._cells) == 1 and self._grid_container is None:
            return
        self._clear_all()
        self._cell = _PreviewCell(self)
        self._cells.append(self._cell)
        self._main.addWidget(self._cell)

    def _build_grid(self, n: int) -> None:
        self._clear_all()

        self._grid_container = QWidget(self)
        if n == 2:
            layout = QHBoxLayout(self._grid_container)
        else:
            # 3 ou 4 : grille 2x2
            outer = QVBoxLayout(self._grid_container)
            outer.setContentsMargins(0, 0, 0, 0)
            top = QHBoxLayout()
            bot = QHBoxLayout()
            outer.addLayout(top)
            outer.addLayout(bot)
            layout = None  # geree manuellement plus bas
        if n == 2 and layout is not None:
            layout.setContentsMargins(0, 0, 0, 0)
            for _ in range(2):
                cell = _PreviewCell(self._grid_container)
                self._cells.append(cell)
                layout.addWidget(cell)
        else:
            # n in (3, 4)
            outer_layout = self._grid_container.layout()
            top_layout = outer_layout.itemAt(0).layout()
            bot_layout = outer_layout.itemAt(1).layout()
            for i in range(n):
                cell = _PreviewCell(self._grid_container)
                self._cells.append(cell)
                (top_layout if i < 2 else bot_layout).addWidget(cell)
            if n == 3:
                # 3eme cellule en bas seule -> ajouter stretch pour ne pas
                # qu'elle prenne toute la largeur
                bot_layout.addStretch()

        self._main.addWidget(self._grid_container)

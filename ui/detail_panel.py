"""Panneau de details (mockup tri) : preview + metadata + mots-cles +
categorie + destination + bouton ouvrir dossier.

Affiche tout ce qui concerne le fichier currentement focalise dans la table.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from PIL import Image
from PyQt6.QtCore import Qt, pyqtSignal, QUrl, QSize
from PyQt6.QtGui import QPixmap, QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QGridLayout, QSizePolicy, QTextEdit, QScrollArea,
)

from core import docs, keywords as _kw, embeddings as _emb
from .styles import (
    CARD, CARD2, BORDER, TEXT, TEXT2, TEXT3, ACCENT, fmt_size, category_color,
)
from .preview import load_thumbnail


class DetailPanel(QWidget):
    """Affiche les details d'1 fichier focalise : preview + metadata + tags."""

    edit_category_requested = pyqtSignal()
    open_dest_requested = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {CARD}; border: 1px solid {BORDER}; border-radius: 8px;"
        )
        self._current_path: Optional[Path] = None
        self._source_pixmap: Optional[QPixmap] = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        title = QLabel("Previsualisation")
        title.setStyleSheet(f"color: {TEXT}; font-size: 14px; font-weight: 700;")
        outer.addWidget(title)

        # Zone preview (image OU texte extrait)
        self.preview_frame = QFrame()
        self.preview_frame.setMinimumHeight(220)
        self.preview_frame.setStyleSheet(
            f"background: {CARD2}; border-radius: 6px;"
        )
        pf_lay = QVBoxLayout(self.preview_frame)
        pf_lay.setContentsMargins(4, 4, 4, 4)
        self.image_lbl = QLabel("Aucun fichier selectionne")
        self.image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 12px;")
        self.image_lbl.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        pf_lay.addWidget(self.image_lbl)
        outer.addWidget(self.preview_frame)

        # Metadata grid : Nom / Type / Taille / Modifie / Resolution / Source
        self.meta_grid = QGridLayout()
        self.meta_grid.setHorizontalSpacing(12)
        self.meta_grid.setVerticalSpacing(4)
        self._meta_rows: dict[str, tuple[QLabel, QLabel]] = {}
        for i, key in enumerate(["Nom :", "Type :", "Taille :", "Modifie le :", "Resolution :", "Source :"]):
            k_lbl = QLabel(key)
            k_lbl.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
            v_lbl = QLabel("-")
            v_lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
            v_lbl.setWordWrap(True)
            v_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.meta_grid.addWidget(k_lbl, i, 0)
            self.meta_grid.addWidget(v_lbl, i, 1)
            self._meta_rows[key] = (k_lbl, v_lbl)
        outer.addLayout(self.meta_grid)

        # Categorie proposee
        cat_row = QHBoxLayout()
        cat_row.addWidget(QLabel("Categorie proposee :"))
        self.cat_badge = QLabel("-")
        self.cat_badge.setStyleSheet(
            f"background: {ACCENT}; color: white; padding: 4px 10px; "
            f"border-radius: 12px; font-size: 11px; font-weight: 700;"
        )
        cat_row.addWidget(self.cat_badge)
        cat_row.addStretch()
        modify_btn = QPushButton("Modifier")
        modify_btn.setProperty("role", "secondary")
        modify_btn.clicked.connect(self.edit_category_requested.emit)
        cat_row.addWidget(modify_btn)
        outer.addLayout(cat_row)

        # Destination proposee
        dest_row = QHBoxLayout()
        dest_block = QVBoxLayout()
        dest_block.addWidget(QLabel("Destination proposee :"))
        self.dest_lbl = QLabel("-")
        self.dest_lbl.setStyleSheet(
            f"color: {ACCENT}; font-size: 11px; padding: 4px 8px; "
            f"background: {CARD2}; border-radius: 4px;"
        )
        self.dest_lbl.setWordWrap(True)
        self.dest_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dest_block.addWidget(self.dest_lbl)
        dest_row.addLayout(dest_block, stretch=1)
        open_btn = QPushButton("Ouvrir dossier")
        open_btn.setProperty("role", "secondary")
        open_btn.clicked.connect(self.open_dest_requested.emit)
        dest_row.addWidget(open_btn, alignment=Qt.AlignmentFlag.AlignBottom)
        outer.addLayout(dest_row)

        # Mots-cles detectes
        outer.addWidget(QLabel("Mots-cles detectes :"))
        self.kw_container = QFrame()
        self.kw_container.setStyleSheet(f"background: transparent;")
        self.kw_layout = QHBoxLayout(self.kw_container)
        self.kw_layout.setContentsMargins(0, 0, 0, 0)
        self.kw_layout.setSpacing(6)
        self.kw_layout.addStretch()
        outer.addWidget(self.kw_container)

        # Section "Pourquoi cette categorie" (top-3 matches semantique)
        outer.addWidget(QLabel("Pourquoi cette categorie ?"))
        self.debug_text = QTextEdit()
        self.debug_text.setReadOnly(True)
        self.debug_text.setMaximumHeight(110)
        self.debug_text.setStyleSheet(
            f"background: {CARD2}; color: {TEXT2}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; font-family: monospace; font-size: 10px; padding: 4px;"
        )
        outer.addWidget(self.debug_text)

        # Info
        info = QLabel("Vous pouvez modifier la categorie ou le dossier de destination avant le deplacement.")
        info.setStyleSheet(f"color: {TEXT3}; font-size: 10px;")
        info.setWordWrap(True)
        outer.addWidget(info)

        outer.addStretch()

    # ------------------------------------------------------------------
    def show_for(
        self,
        path: Path,
        category: str,
        destination: str,
        reason: str = "",
        confidence: float = 0.0,
    ) -> None:
        self._current_path = path
        self._destination = destination

        # Preview image / doc
        kind = docs.kind_of(path)
        if kind == "image":
            pm = load_thumbnail(path, max_size=(800, 800))
            self._source_pixmap = pm
            self._rescale_preview()
        else:
            self._source_pixmap = None
            text = docs.extract_text(path, max_chars=500) or "(aucun texte extrait)"
            self.image_lbl.setText(text[:300] + ("..." if len(text) > 300 else ""))
            self.image_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self.image_lbl.setStyleSheet(f"color: {TEXT}; font-size: 10px; padding: 4px;")
            self.image_lbl.setWordWrap(True)

        # Metadata
        try:
            st = path.stat()
            size_str = fmt_size(st.st_size)
            from datetime import datetime
            mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M")
        except OSError:
            size_str, mtime = "-", "-"
        # Resolution si image
        res = "-"
        if kind == "image":
            try:
                with Image.open(path) as img:
                    res = f"{img.size[0]} x {img.size[1]}"
            except Exception:  # noqa: BLE001
                pass
        self._meta_rows["Nom :"][1].setText(path.name)
        self._meta_rows["Type :"][1].setText(kind.upper() if kind != "other" else path.suffix.upper())
        self._meta_rows["Taille :"][1].setText(size_str)
        self._meta_rows["Modifie le :"][1].setText(mtime)
        self._meta_rows["Resolution :"][1].setText(res)
        self._meta_rows["Source :"][1].setText(str(path))

        # Categorie badge
        bg, fg = category_color(category)
        self.cat_badge.setText(category)
        self.cat_badge.setStyleSheet(
            f"background: {bg}; color: {fg}; padding: 4px 10px; "
            f"border-radius: 12px; font-size: 11px; font-weight: 700;"
        )
        if confidence > 0 or reason:
            self.cat_badge.setToolTip(
                f"Confiance : {int(confidence*100)}%  ·  Raison : {reason}"
            )

        # Destination
        self.dest_lbl.setText(destination or "(non defini)")

        # Mots-cles (async serait ideal mais V1 : sync)
        try:
            kws = _kw.keywords_for(path, top_n=6)
        except Exception:  # noqa: BLE001
            kws = []
        self._render_keywords(kws)

        # Debug : top-3 matches semantiques + raison
        debug_lines = [f"Raison : {reason or '(inconnue)'}"]
        debug_lines.append(f"Confiance : {int(confidence * 100)}%")
        if _emb.embeddings_available():
            try:
                from core import exemplars as _ex
                store = _ex.ExemplarStore.get()
                kind = docs.kind_of(path)
                img_p = path if kind == "image" else None
                text = ""
                if kind in ("pdf", "docx", "xlsx"):
                    text = docs.extract_text(path, max_chars=2000) or ""
                elif kind == "image":
                    try:
                        from core import sort
                        text = sort.ocr_text(path)
                    except Exception:  # noqa: BLE001
                        text = ""
                txt = text if text and len(text.strip()) >= 5 else None
                matches = store.best_match_combined(img_p, txt, top_n=3)
                if matches:
                    debug_lines.append("")
                    debug_lines.append("Top-3 sémantique :")
                    for f, s in matches:
                        ni, nt = store.exemplar_count(f)
                        debug_lines.append(f"  {f}  {s:.3f}  ({ni} img / {nt} txt)")
                else:
                    debug_lines.append("")
                    debug_lines.append("(aucun dossier connu — utilise Apprentissage)")
            except Exception as e:  # noqa: BLE001
                debug_lines.append(f"(erreur : {e})")
        self.debug_text.setPlainText("\n".join(debug_lines))

    def _render_keywords(self, kws: list[str]) -> None:
        # Clear
        while self.kw_layout.count():
            it = self.kw_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if not kws:
            lbl = QLabel("(aucun mot-cle detecte)")
            lbl.setStyleSheet(f"color: {TEXT3}; font-size: 10px; font-style: italic;")
            self.kw_layout.addWidget(lbl)
        else:
            for k in kws:
                chip = QLabel(k)
                chip.setStyleSheet(
                    f"background: {CARD2}; color: {TEXT}; padding: 3px 10px; "
                    f"border: 1px solid {BORDER}; border-radius: 12px; font-size: 10px;"
                )
                self.kw_layout.addWidget(chip)
        self.kw_layout.addStretch()

    def _rescale_preview(self) -> None:
        if self._source_pixmap is None:
            return
        target = self.preview_frame.size()
        if target.width() <= 0 or target.height() <= 0:
            self.image_lbl.setPixmap(self._source_pixmap)
            return
        # Marge interne
        target = QSize(max(50, target.width() - 16), max(50, target.height() - 16))
        scaled = self._source_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.image_lbl.setPixmap(scaled)
        self.image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_lbl.setStyleSheet("background: transparent;")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._source_pixmap is not None:
            self._rescale_preview()

    def clear(self) -> None:
        self._current_path = None
        self._source_pixmap = None
        self.image_lbl.clear()
        self.image_lbl.setText("Aucun fichier selectionne")
        self.image_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 12px;")
        for _, (_, v) in self._meta_rows.items():
            v.setText("-")
        self.cat_badge.setText("-")
        self.dest_lbl.setText("-")
        self._render_keywords([])
        self.debug_text.setPlainText("")

    def get_destination(self) -> str:
        return getattr(self, "_destination", "")

    def get_current_path(self) -> Optional[Path]:
        return self._current_path

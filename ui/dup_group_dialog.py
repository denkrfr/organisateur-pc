"""Dialog 'Voir/Modifier la selection' pour un groupe de doublons.

Affiche tous les fichiers du groupe en grille de thumbnails avec checkboxes
individuelles + actions rapides (cocher sauf le + gros, decocher tout).
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QIcon, QDesktopServices
from PyQt6.QtCore import QUrl
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QListWidget,
    QListWidgetItem, QDialogButtonBox, QFrame, QCheckBox, QScrollArea, QWidget,
)

from core import docs
from core.models import Asset, DupGroup
from .styles import (
    fmt_size, TEXT, TEXT2, TEXT3, CARD, CARD2, BORDER, ACCENT, ACCENT2, OK, DANGER,
)
from .preview import load_thumbnail


class DupGroupContentsDialog(QDialog):
    """Liste tous les fichiers d'un groupe doublons avec checkbox individuelle.

    Apres exec(), si OK :
      self.checked_indices = indices des fichiers a supprimer (cocher = supprimer)
    """

    def __init__(self, group: DupGroup, initial_checks: list[bool], parent=None) -> None:
        super().__init__(parent)
        self.group = group
        self._checks = list(initial_checks)
        self.setWindowTitle(
            f"Groupe de {len(group.items)} fichiers ({group.kind})"
        )
        self.setMinimumSize(820, 600)
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(10)

        # Header
        title = QLabel(
            f"{len(self.group.items)} fichiers - "
            f"{fmt_size(self.group.total_recoverable)} recuperables si tu coches tous sauf le + gros"
        )
        title.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 600;")
        title.setWordWrap(True)
        outer.addWidget(title)

        info = QLabel(
            "✓ Coche un fichier = il sera ENVOYE A LA CORBEILLE. "
            "Decoche pour le garder. Le + gros (en haut) est generalement la meilleure copie."
        )
        info.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        info.setWordWrap(True)
        outer.addWidget(info)

        # Actions rapides
        actions = QHBoxLayout()
        keep_btn = QPushButton("Cocher tout sauf le + gros")
        keep_btn.clicked.connect(self._check_all_but_first)
        actions.addWidget(keep_btn)
        none_btn = QPushButton("Tout decocher")
        none_btn.setProperty("role", "secondary")
        none_btn.clicked.connect(self._uncheck_all)
        actions.addWidget(none_btn)
        all_btn = QPushButton("Tout cocher")
        all_btn.setProperty("role", "secondary")
        all_btn.clicked.connect(self._check_all)
        actions.addWidget(all_btn)
        actions.addStretch()
        self.count_lbl = QLabel("")
        self.count_lbl.setStyleSheet(f"color: {TEXT}; font-size: 12px;")
        actions.addWidget(self.count_lbl)
        outer.addLayout(actions)

        # Scroll area avec les fichiers
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self.container_layout = QVBoxLayout(container)
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        self.container_layout.setSpacing(4)
        self._file_rows: list[QFrame] = []
        self._checkboxes: list[QCheckBox] = []
        for i, asset in enumerate(self.group.items):
            row = self._make_file_row(i, asset)
            self.container_layout.addWidget(row)
            self._file_rows.append(row)
        self.container_layout.addStretch()
        self.scroll.setWidget(container)
        outer.addWidget(self.scroll, stretch=1)

        # Buttons OK/Cancel
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Valider la selection")
        btns.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        outer.addWidget(btns)

        self._update_count()

    def _make_file_row(self, idx: int, asset: Asset) -> QFrame:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: 6px; padding: 6px; }}"
        )
        h = QHBoxLayout(row)
        h.setContentsMargins(8, 6, 8, 6)
        h.setSpacing(10)

        # Checkbox
        cb = QCheckBox()
        cb.setChecked(self._checks[idx])
        cb.toggled.connect(lambda c, i=idx: self._on_toggled(i, c))
        h.addWidget(cb)
        self._checkboxes.append(cb)

        # Thumbnail (charge lazy : ici on charge directement, mais limite a 64px)
        thumb = QLabel()
        thumb.setFixedSize(64, 64)
        thumb.setStyleSheet(
            f"background: {CARD2}; border-radius: 4px; "
            f"color: {ACCENT}; font-size: 12px; font-weight: 700;"
        )
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kind = docs.kind_of(asset.path)
        if kind == "image":
            try:
                pm = load_thumbnail(asset.path, max_size=(128, 128))
                if pm is not None:
                    scaled = pm.scaled(
                        QSize(62, 62), Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    thumb.setPixmap(scaled)
            except Exception:  # noqa: BLE001
                thumb.setText("?")
        else:
            # Icones pour les non-images. Video = badge violet specifique.
            icons = {"pdf": "PDF", "docx": "DOC", "xlsx": "XLS", "video": "VIDEO"}
            thumb.setText(icons.get(kind, "?"))
            if kind == "video":
                thumb.setStyleSheet(
                    f"background: #7c3aed; color: white; border-radius: 4px; "
                    f"font-size: 11px; font-weight: 800;"
                )
        # Click on thumb = ouvre fichier (defensif : pas de crash si Windows
        # refuse d'ouvrir le format ou si le fichier a disparu entre-temps)
        def _safe_open_click(_e, p=asset.path) -> None:
            try:
                if not p.exists():
                    return
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))
            except Exception as ex:  # noqa: BLE001
                print(f"[DupGroupContentsDialog] openUrl error: {ex}")
        thumb.mousePressEvent = _safe_open_click
        thumb.setCursor(Qt.CursorShape.PointingHandCursor)
        thumb.setToolTip("Clique pour ouvrir le fichier")
        h.addWidget(thumb)

        # Info colonne : nom + taille + chemin + tag "le + gros" si idx 0
        info_col = QVBoxLayout()
        info_col.setSpacing(2)
        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name = QLabel(asset.path.name)
        name.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px;")
        name.setToolTip(asset.path.name)
        name_row.addWidget(name)
        size_lbl = QLabel(fmt_size(asset.size))
        size_lbl.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        name_row.addWidget(size_lbl)
        if idx == 0:
            tag = QLabel("Meilleure copie (plus volumineuse)")
            tag.setStyleSheet(
                f"background: {OK}; color: black; padding: 2px 8px; "
                f"border-radius: 3px; font-size: 10px; font-weight: 700;"
            )
            tag.setToolTip(
                "Cette copie est la plus volumineuse du groupe. "
                "Generalement la version originale (moins compressee). "
                "Recommandation : la garder, supprimer les autres."
            )
            name_row.addWidget(tag)
        name_row.addStretch()
        info_col.addLayout(name_row)
        path_lbl = QLabel(str(asset.path))
        path_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 10px;")
        path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_lbl.setToolTip(str(asset.path))
        info_col.addWidget(path_lbl)
        h.addLayout(info_col, stretch=1)

        return row

    def _on_toggled(self, idx: int, checked: bool) -> None:
        self._checks[idx] = checked
        self._update_count()

    def _check_all_but_first(self) -> None:
        for i, cb in enumerate(self._checkboxes):
            cb.setChecked(i != 0)

    def _check_all(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(True)

    def _uncheck_all(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _update_count(self) -> None:
        n = sum(1 for c in self._checks if c)
        size = sum(
            a.size for a, c in zip(self.group.items, self._checks) if c
        )
        self.count_lbl.setText(
            f"{n} / {len(self.group.items)} a supprimer ({fmt_size(size)})"
        )

    @property
    def checked_indices(self) -> list[bool]:
        return list(self._checks)

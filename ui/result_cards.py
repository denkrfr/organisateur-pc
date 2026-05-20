"""Widgets visuels pour les resultats Dedup et Tri.

Note: pour les strings i18n, on utilise t() de core/i18n. Les strings sont
traduites a l'instanciation, donc un changement de langue necessite un
redemarrage de l'app pour s'appliquer aux widgets deja construits.


Composants :
  - ThumbnailCard    : (legacy) 1 fichier en mode carte verticale
  - DupGroupCard     : (legacy) 1 groupe de doublons en mode carte verticale
  - SortFileCard     : (legacy) 1 fichier a trier en carte verticale
  - DupGroupRow      : NEW 1 groupe de doublons en ligne horizontale (mockup)
  - SortFileRow      : NEW 1 fichier en ligne de tableau (mockup)
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QSize, QUrl
from PyQt6.QtGui import QPixmap, QDesktopServices, QMouseEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QFrame,
    QScrollArea, QPushButton, QSizePolicy, QLineEdit, QCompleter,
)

from core import docs
from core.i18n import t
from core.models import Asset, DupGroup
from .styles import (
    fmt_size, CARD, CARD2, BORDER, TEXT, TEXT2, TEXT3, ACCENT, ACCENT2,
    OK, WARN, DANGER, category_color,
)
from .preview import load_thumbnail


THUMB_W = 200
THUMB_H = 150
CARD_W = 220


def _elide_path(p: Path, max_chars: int = 40) -> str:
    """Tronque un chemin pour affichage : C:\\Users\\...\\folder\\file.png.
    Garde toujours visible le nom de fichier + le dossier parent.
    Utilise le separateur natif de la plateforme (os.sep)."""
    import os
    s = str(p)
    if len(s) <= max_chars:
        return s
    sep = os.sep
    tail = f"{p.parent.name}{sep}{p.name}" if p.parent.name else p.name
    if len(tail) >= max_chars - 4:
        return "..." + tail[-(max_chars - 3):]
    head_keep = max_chars - len(tail) - 4
    if head_keep < 3:
        return "..." + tail
    return s[:head_keep] + "..." + s[-(len(tail) + 1):]


# ---------------------------------------------------------------------------
# ThumbnailCard — 1 fichier (image ou doc)
# ---------------------------------------------------------------------------
class ThumbnailCard(QFrame):
    """Vignette d'un fichier : thumbnail + nom + taille + chemin + check."""

    toggled = pyqtSignal(object, bool)  # (Asset, is_checked)

    def __init__(
        self,
        asset: Asset,
        is_biggest: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.asset = asset
        self.is_biggest = is_biggest
        self.setFixedWidth(CARD_W)
        self.setObjectName("ThumbnailCard")
        self.setStyleSheet(
            f"#ThumbnailCard {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: 6px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Thumbnail (clickable -> open default app)
        self.thumb = _ClickableLabel(asset.path)
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(
            f"background: {CARD2}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        self._render_thumb()
        layout.addWidget(self.thumb)

        # Nom de fichier (tronque visuellement par Qt)
        name = QLabel(asset.path.name)
        name.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px;")
        name.setWordWrap(False)
        name.setToolTip(asset.path.name)
        layout.addWidget(name)

        # Taille + badge biggest
        meta_row = QHBoxLayout()
        meta_row.setSpacing(6)
        size_lbl = QLabel(fmt_size(asset.size))
        size_lbl.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        meta_row.addWidget(size_lbl)
        meta_row.addStretch()
        if is_biggest:
            badge = QLabel(t("group.keep"))
            badge.setStyleSheet(
                f"background: {OK}; color: black; padding: 2px 7px; "
                f"border-radius: 3px; font-size: 10px; font-weight: 700;"
            )
            badge.setToolTip("Version la plus volumineuse, generalement l'originale. Recommande de la garder.")
            meta_row.addWidget(badge)
        layout.addLayout(meta_row)

        # Chemin tronque intelligent. Tooltip + selectable pour copier le full.
        path_lbl = QLabel(_elide_path(asset.path, max_chars=36))
        path_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 10px;")
        path_lbl.setWordWrap(False)
        path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_lbl.setToolTip(str(asset.path))
        layout.addWidget(path_lbl)

        # Checkbox
        self.checkbox = QCheckBox(t("dedup.trash_btn"))
        if is_biggest:
            self.checkbox.setStyleSheet(f"color: {TEXT2};")
        self.checkbox.toggled.connect(self._on_toggled)
        layout.addWidget(self.checkbox)

    # ------------------------------------------------------------------
    def _render_thumb(self) -> None:
        kind = docs.kind_of(self.asset.path)
        # Images ET videos : on tente la preview. load_thumbnail delegue
        # automatiquement aux extracteurs corrects (Qt/Pillow pour images,
        # ffmpeg pour videos).
        if kind in ("image", "video"):
            pm = load_thumbnail(self.asset.path, max_size=(THUMB_W * 2, THUMB_H * 2))
            if pm is not None:
                scaled = pm.scaled(
                    QSize(THUMB_W - 4, THUMB_H - 4),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb.setPixmap(scaled)
                return
        # Fallback : icone + label de type pour les docs (et videos si ffmpeg
        # n'a pas pu extraire la frame)
        icons = {"pdf": "PDF", "docx": "DOC", "xlsx": "XLS", "video": "VIDEO", "other": "FILE"}
        label = icons.get(kind, "?")
        self.thumb.setText(label)
        # Style different pour les videos : badge violet pour distinguer
        if kind == "video":
            self.thumb.setStyleSheet(
                f"background: #7c3aed; color: white; border-radius: 4px; "
                f"font-size: 18px; font-weight: 800;"
            )
        else:
            self.thumb.setStyleSheet(
                f"background: {CARD2}; border: 1px solid {BORDER}; border-radius: 4px;"
                f"color: {ACCENT}; font-size: 28px; font-weight: 800;"
            )

    def _on_toggled(self, checked: bool) -> None:
        self.toggled.emit(self.asset, checked)

    def set_checked(self, checked: bool) -> None:
        # Bloque le signal pour ne pas declencher de cascade
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()


class _ClickableLabel(QLabel):
    """QLabel qui ouvre le fichier dans l'app par defaut au clic.

    Ultra-defensif : si l'ouverture echoue ou crash au niveau OS (shell
    Windows en vrac, file lock, codec absent, etc.), on log et on affiche
    une popup au lieu de laisser l'exception remonter dans Qt et tuer l'app.
    """

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._path = path
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Cliquer pour ouvrir avec l'app par defaut")

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if ev.button() == Qt.MouseButton.LeftButton:
            self._safe_open()
        try:
            super().mousePressEvent(ev)
        except Exception:  # noqa: BLE001
            # On laisse pas une exception du parent Qt tuer l'app
            pass

    def _safe_open(self) -> None:
        """Tente d'ouvrir le fichier sans jamais laisser une exception remonter."""
        try:
            if not self._path.exists():
                # Fichier supprime entre-temps (envoye a la corbeille par ex)
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.warning(
                    None, "Fichier introuvable",
                    f"Le fichier n'existe plus :\n{self._path.name}\n\n"
                    "Il a peut-etre ete deplace, renomme ou envoye a la corbeille."
                )
                return
            ok = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._path)))
            if not ok:
                # Windows n'a pas pu ouvrir (pas d'app associee a l'extension, etc.)
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.information(
                    None, "Impossible d'ouvrir",
                    f"Windows n'a pas pu ouvrir ce fichier automatiquement :\n"
                    f"{self._path.name}\n\n"
                    f"Tu peux le verifier dans l'explorateur :\n{self._path.parent}"
                )
        except Exception as e:  # noqa: BLE001
            # Log dans la console + popup, jamais de crash
            print(f"[ClickableLabel] Erreur openUrl pour {self._path}: {e}")
            try:
                from PyQt6.QtWidgets import QMessageBox
                QMessageBox.critical(
                    None, "Erreur d'ouverture",
                    f"Erreur en ouvrant le fichier :\n{self._path.name}\n\n{e}"
                )
            except Exception:  # noqa: BLE001
                pass  # meme la popup a foire, on abandonne


# ---------------------------------------------------------------------------
# DupGroupCard — 1 groupe de doublons (header + ligne de vignettes)
# ---------------------------------------------------------------------------
class DupGroupCard(QFrame):
    """Affiche un groupe : header (kind + % match + recovery) + thumbnails."""

    item_toggled = pyqtSignal(object, bool)  # (Asset, checked)

    def __init__(self, group: DupGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self.setObjectName("DupGroupCard")
        self.setStyleSheet(
            f"#DupGroupCard {{ background: transparent; border: 1px solid {BORDER}; "
            f"border-radius: 8px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 12)
        layout.setSpacing(8)

        # Header
        header = QHBoxLayout()
        kind_color = ACCENT if group.kind == "exact" else WARN
        kind_text_color = "white" if group.kind == "exact" else "black"
        match_pct = self._compute_match_pct()
        kind_badge = QLabel(f" {group.kind.upper()}  {match_pct}% ")
        kind_badge.setStyleSheet(
            f"background: {kind_color}; color: {kind_text_color}; "
            f"padding: 3px 10px; border-radius: 4px; font-weight: 700; font-size: 11px;"
        )
        header.addWidget(kind_badge)
        info = QLabel(
            f"{len(group.items)} copies  ·  {fmt_size(group.total_recoverable)} a recuperer"
        )
        info.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 13px;")
        header.addWidget(info)
        header.addStretch()

        # Boutons rapide groupe
        keep_btn = QPushButton(t("dedup.bulk_keep_biggest"))
        keep_btn.setProperty("role", "secondary")
        keep_btn.clicked.connect(self.check_all_but_biggest)
        header.addWidget(keep_btn)
        uncheck_btn = QPushButton(t("dedup.bulk_uncheck"))
        uncheck_btn.setProperty("role", "secondary")
        uncheck_btn.clicked.connect(self.uncheck_all)
        header.addWidget(uncheck_btn)
        layout.addLayout(header)

        # Ligne horizontale de vignettes, scroll horizontal si trop large
        thumbs_scroll = QScrollArea()
        thumbs_scroll.setWidgetResizable(True)
        thumbs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        thumbs_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        thumbs_scroll.setFrameShape(QFrame.Shape.NoFrame)
        thumbs_scroll.setFixedHeight(290)

        container = QWidget()
        container.setStyleSheet("background: transparent;")
        h = QHBoxLayout(container)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        self.cards: list[ThumbnailCard] = []
        biggest = group.items[0]  # items sont tries par taille desc en amont
        for asset in group.items:
            card = ThumbnailCard(asset, is_biggest=(asset is biggest))
            card.toggled.connect(self.item_toggled.emit)
            self.cards.append(card)
            h.addWidget(card)
        h.addStretch()

        thumbs_scroll.setWidget(container)
        layout.addWidget(thumbs_scroll)

    # ------------------------------------------------------------------
    def _compute_match_pct(self) -> int:
        if self.group.kind == "exact":
            return 100
        items = self.group.items
        # Quasi docs : meme texte normalise = 100% match contenu
        if items and items[0].text_hash is not None:
            return 100
        # Quasi images : moyenne distance Hamming
        if items and items[0].a_hash is not None:
            ref = items[0].a_hash
            distances = []
            for it in items[1:]:
                if it.a_hash is not None:
                    distances.append(bin(ref ^ it.a_hash).count("1"))
            if distances:
                avg = sum(distances) / len(distances)
                return int(round((64 - avg) / 64 * 100))
        return 95  # fallback

    def check_all_but_biggest(self) -> None:
        for i, c in enumerate(self.cards):
            c.set_checked(i != 0)  # i==0 = le + gros (sorted desc)
        # Re-emet pour que le parent recalcule le total
        for c in self.cards:
            self.item_toggled.emit(c.asset, c.is_checked())

    def uncheck_all(self) -> None:
        for c in self.cards:
            was_checked = c.is_checked()
            c.set_checked(False)
            if was_checked:
                self.item_toggled.emit(c.asset, False)

    def checked_cards(self) -> list[ThumbnailCard]:
        return [c for c in self.cards if c.is_checked()]

    def remove_card(self, card: ThumbnailCard) -> None:
        if card in self.cards:
            self.cards.remove(card)
            card.setParent(None)
            card.deleteLater()


# ---------------------------------------------------------------------------
# SortFileCard — 1 fichier a trier (vignette + categorie + dossier)
# ---------------------------------------------------------------------------
class SortFileCard(QFrame):
    """Vignette d'un fichier a trier avec sa categorie proposee et le dossier cible."""

    selection_changed = pyqtSignal()  # signal generique pour update footer
    edit_requested = pyqtSignal(object)  # (SortFileCard) - double clic pour editer dossier

    def __init__(
        self,
        path: Path,
        category: str,
        folder: str,
        confidence: float,
        reason: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.folder = folder
        self.category = category
        self.confidence = confidence
        self.reason = reason
        self.setFixedWidth(CARD_W)
        self.setObjectName("SortFileCard")
        self.setStyleSheet(
            f"#SortFileCard {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: 6px; }}"
            f"#SortFileCard[selected=\"true\"] {{ border: 2px solid {ACCENT}; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        # Thumbnail (clic = ouvrir externe, dblclic via la card = edit dossier)
        self.thumb = _ClickableLabel(path)
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(
            f"background: {CARD2}; border: 1px solid {BORDER}; border-radius: 4px;"
        )
        self._render_thumb()
        layout.addWidget(self.thumb)

        name = QLabel(path.name)
        name.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px;")
        name.setToolTip(path.name)
        layout.addWidget(name)

        # Chemin tronque intelligent. Tooltip + selectable pour copier le full.
        path_lbl = QLabel(_elide_path(path, max_chars=36))
        path_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 10px;")
        path_lbl.setWordWrap(False)
        path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        path_lbl.setToolTip(str(path))
        layout.addWidget(path_lbl)

        # Categorie + confiance
        cat_row = QHBoxLayout()
        cat_row.setSpacing(6)
        cat_badge = QLabel(f" {category} ")
        cat_color = OK if confidence >= 0.7 else (WARN if confidence >= 0.3 else DANGER)
        cat_badge.setStyleSheet(
            f"background: {cat_color}; color: black; padding: 2px 6px; "
            f"border-radius: 3px; font-weight: 700; font-size: 10px;"
        )
        cat_row.addWidget(cat_badge)
        conf_lbl = QLabel(f"{int(confidence * 100)}%")
        conf_lbl.setStyleSheet(f"color: {TEXT2}; font-size: 10px;")
        cat_row.addWidget(conf_lbl)
        cat_row.addStretch()
        # Bouton info pour voir pourquoi cette categorie + texte OCR
        info_btn = QPushButton("?")
        info_btn.setProperty("role", "secondary")
        info_btn.setFixedSize(22, 22)
        info_btn.setToolTip("Voir pourquoi cette categorie et le texte detecte")
        info_btn.clicked.connect(self._show_debug_info)
        cat_row.addWidget(info_btn)
        layout.addLayout(cat_row)

        # Raison (petit texte gris, visible direct)
        if reason:
            reason_lbl = QLabel(f"via : {reason}")
            reason_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 9px; font-style: italic;")
            reason_lbl.setWordWrap(True)
            layout.addWidget(reason_lbl)

        # Dossier propose — affichage editable directement (1 ligne) + bouton
        folder_row = QHBoxLayout()
        folder_row.setSpacing(4)
        self.folder_input = QLineEdit(folder)
        self.folder_input.setStyleSheet(
            f"background: {CARD2}; color: {ACCENT}; border: 1px solid {BORDER}; "
            f"border-radius: 3px; padding: 4px; font-weight: 600; font-size: 11px;"
        )
        self.folder_input.setToolTip("Tape ici ton nom de dossier, ou clique sur le bouton pour la liste")
        self.folder_input.editingFinished.connect(self._on_folder_text_changed)
        folder_row.addWidget(self.folder_input, stretch=1)

        pick_btn = QPushButton("...")
        pick_btn.setProperty("role", "secondary")
        pick_btn.setFixedWidth(36)
        pick_btn.setToolTip("Choisir parmi les dossiers deja utilises")
        pick_btn.clicked.connect(self._request_picker)
        folder_row.addWidget(pick_btn)
        layout.addLayout(folder_row)

        # Checkbox pour selection bulk
        self.checkbox = QCheckBox("Inclure dans le deplacement")
        self.checkbox.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        self.checkbox.toggled.connect(lambda _c: self.selection_changed.emit())
        layout.addWidget(self.checkbox)

        self._selected_visual = False

    def _render_thumb(self) -> None:
        kind = docs.kind_of(self.path)
        # Images ET videos : on tente la preview
        if kind in ("image", "video"):
            pm = load_thumbnail(self.path, max_size=(THUMB_W * 2, THUMB_H * 2))
            if pm is not None:
                scaled = pm.scaled(
                    QSize(THUMB_W - 4, THUMB_H - 4),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.thumb.setPixmap(scaled)
                return
        icons = {"pdf": "PDF", "docx": "DOC", "xlsx": "XLS", "video": "VIDEO", "other": "FILE"}
        label = icons.get(kind, "?")
        self.thumb.setText(label)
        if kind == "video":
            self.thumb.setStyleSheet(
                f"background: #7c3aed; color: white; border-radius: 4px; "
                f"font-size: 18px; font-weight: 800;"
            )
        else:
            self.thumb.setStyleSheet(
                f"background: {CARD2}; border: 1px solid {BORDER}; border-radius: 4px;"
                f"color: {ACCENT}; font-size: 28px; font-weight: 800;"
            )

    def set_folder(self, folder: str) -> None:
        self.folder = folder
        self.folder_input.setText(folder)

    def set_known_folders(self, folders: list[str]) -> None:
        """Active l'autocomplete inline sur le champ dossier."""
        completer = QCompleter(folders, self.folder_input)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.folder_input.setCompleter(completer)

    def _on_folder_text_changed(self) -> None:
        new_val = self.folder_input.text().strip()
        if new_val != self.folder:
            self.folder = new_val

    def _request_picker(self) -> None:
        # Demande au parent (SortView) d'ouvrir le picker avec autocomplete
        self.edit_requested.emit(self)

    def _show_debug_info(self) -> None:
        """Affiche les infos de detection : raison, top-3 semantique, texte OCR/extrait."""
        from PyQt6.QtWidgets import QMessageBox, QTextEdit, QDialog, QVBoxLayout, QLabel as _Lbl
        from core import sort, docs, embeddings

        kind = docs.kind_of(self.path)
        if kind == "image":
            extracted = sort.ocr_text(self.path)
            source = "OCR Tesseract"
        elif kind in ("pdf", "docx", "xlsx"):
            extracted = docs.extract_text(self.path, max_chars=10_000) or ""
            source = f"Extraction {kind.upper()}"
        else:
            extracted = ""
            source = "Aucune extraction"

        # Top-3 matches semantiques
        sem_block = ""
        if embeddings.embeddings_available():
            try:
                from core import exemplars as _ex
                store = _ex.ExemplarStore.get()
                img_path = self.path if kind == "image" else None
                txt = extracted if extracted and len(extracted.strip()) >= 5 else None
                matches = store.best_match_combined(img_path, txt, top_n=5)
                if matches:
                    lines = ["Top matches semantiques (CLIP + E5) :"]
                    for f, s in matches:
                        ni, nt = store.exemplar_count(f)
                        lines.append(f"  - {f}  score={s:.3f}  (exemplars: {ni} img / {nt} txt)")
                    sem_block = "\n".join(lines)
                else:
                    sem_block = "Top matches semantiques : aucun (pas d'exemplars dans le store)."
            except Exception as e:  # noqa: BLE001
                sem_block = f"Erreur semantique : {e}"
        else:
            sem_block = "Embeddings non disponibles."

        dlg = QDialog(self)
        dlg.setWindowTitle("Pourquoi cette categorie ?")
        dlg.setMinimumWidth(640)
        layout = QVBoxLayout(dlg)
        layout.addWidget(_Lbl(f"<b>Fichier :</b> {self.path.name}"))
        layout.addWidget(_Lbl(f"<b>Categorie proposee :</b> {self.category}  ({int(self.confidence*100)}%)"))
        layout.addWidget(_Lbl(f"<b>Dossier propose :</b> {self.folder}"))
        layout.addWidget(_Lbl(f"<b>Raison :</b> {self.reason or '(inconnue)'}"))
        layout.addWidget(_Lbl(""))
        sem_text = QTextEdit()
        sem_text.setReadOnly(True)
        sem_text.setPlainText(sem_block)
        sem_text.setMaximumHeight(160)
        sem_text.setStyleSheet("font-family: monospace; font-size: 11px;")
        layout.addWidget(sem_text)

        layout.addWidget(_Lbl(f"<b>Texte detecte ({source}) :</b>"))
        te = QTextEdit()
        te.setReadOnly(True)
        te.setPlainText(extracted or "(aucun texte detecte — c'est probablement pourquoi ca tombe en Other)")
        te.setMinimumHeight(180)
        layout.addWidget(te)

        from PyQt6.QtWidgets import QDialogButtonBox
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        layout.addWidget(btns)
        dlg.exec()

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool) -> None:
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)

    def mouseDoubleClickEvent(self, ev) -> None:  # noqa: N802
        # Double clic n'importe ou sur la carte = edit dossier
        self.edit_requested.emit(self)
        super().mouseDoubleClickEvent(ev)


# ===========================================================================
# NEW DESIGN (mockup) : rangees horizontales au lieu de cartes verticales
# ===========================================================================

# Couleurs des icones doc-types (pour les placeholders)
_DOC_COLORS = {
    "pdf":   ("#dc2626", "PDF"),    # rouge
    "docx":  ("#2563eb", "DOC"),    # bleu
    "xlsx":  ("#16a34a", "XLS"),    # vert
    "video": ("#7c3aed", "VIDEO"),  # violet
}

ROW_THUMB_SIZE = 64


def make_mini_thumbnail(path: Path, size: int = ROW_THUMB_SIZE) -> QLabel:
    """Mini thumbnail (carre) pour les vues en ligne. Image / video / icone de doc."""
    lbl = _ClickableLabel(path)
    lbl.setFixedSize(size, size)
    lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    kind = docs.kind_of(path)
    # Images : direct via load_thumbnail
    # Videos : load_thumbnail delegue a video_thumb (ffmpeg) qui retourne
    # une frame extraite. Si echec -> fallback badge plus bas.
    if kind in ("image", "video"):
        pm = load_thumbnail(path, max_size=(size * 2, size * 2))
        if pm is not None:
            scaled = pm.scaled(
                QSize(size - 2, size - 2),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            lbl.setPixmap(scaled)
            lbl.setStyleSheet(
                f"background: {CARD2}; border: 1px solid {BORDER}; border-radius: 4px;"
            )
            return lbl
    # Doc placeholder (et fallback video si ffmpeg pas dispo / a echoue)
    if kind in _DOC_COLORS:
        color, label = _DOC_COLORS[kind]
        lbl.setText(label)
        lbl.setStyleSheet(
            f"background: {color}; color: white; border-radius: 4px; "
            f"font-size: 14px; font-weight: 800;"
        )
    else:
        lbl.setText("?")
        lbl.setStyleSheet(
            f"background: {CARD2}; color: {TEXT2}; border-radius: 4px; "
            f"font-size: 16px; font-weight: 700;"
        )
    return lbl


# ---------------------------------------------------------------------------
# DupGroupRow — 1 groupe de doublons en ligne horizontale (mockup)
# ---------------------------------------------------------------------------
class DupGroupRow(QFrame):
    """Ligne horizontale pour 1 groupe de doublons. Layout (de gauche a droite):

        [chk] [N] [thumb1][thumb2]  [fichier1: nom / taille / chemin]   [recap]  [v]
                                    [fichier2: nom / taille / chemin]
                                    ...

    Quand collapsed, n'affiche que 2 lignes de fichiers preview. Quand expand,
    affiche tous + checkbox individuelle par fichier.
    """

    selection_changed = pyqtSignal()  # le check global du groupe a change

    # Seuil : si <= INLINE_THRESHOLD fichiers, affichage direct avec checkboxes
    # individuelles. Sinon : preview de 2 + bouton "Voir / Modifier".
    INLINE_THRESHOLD = 4

    def __init__(self, group: DupGroup, index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.group = group
        self.index = index
        self._expanded = False
        # is_small_group : assez petit pour tout afficher inline avec checkboxes
        self._is_small = len(group.items) <= self.INLINE_THRESHOLD
        # set_checked initial : tout coche sauf le + gros (pattern user le + courant)
        # Mais on commence False : le user clique "Tous groupes: cocher sauf le + gros"
        self._file_checks: list[bool] = [False] * len(group.items)

        self.setObjectName("DupGroupRow")
        self.setStyleSheet(
            f"#DupGroupRow {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: 8px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(6)

        # === Ligne principale (header avec badge + recap) ===
        main_row = QHBoxLayout()
        main_row.setSpacing(10)

        # Checkbox globale (utilisee pour le bouton "tous groupes : cocher sauf le + gros")
        # Cachee visuellement pour les small groups (chaque fichier a sa propre checkbox)
        self.master_check = QCheckBox()
        self.master_check.setChecked(True)
        self.master_check.toggled.connect(self._on_master_toggled)
        if self._is_small:
            self.master_check.setVisible(False)
        main_row.addWidget(self.master_check)

        # Badge numerique
        badge = QLabel(str(index))
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {ACCENT}; color: white; border-radius: 6px; "
            f"font-weight: 800; font-size: 13px;"
        )
        main_row.addWidget(badge)

        # 2 thumbnails apercu en haut (uniquement pour les gros groupes, sinon
        # redondant avec les thumbnails inline)
        if not self._is_small:
            thumbs_row = QHBoxLayout()
            thumbs_row.setSpacing(4)
            for i, asset in enumerate(group.items[:2]):
                thumb_widget = make_mini_thumbnail(asset.path)
                thumbs_row.addWidget(thumb_widget)
            main_row.addLayout(thumbs_row)

        # Liste verticale des fichiers
        self.files_container = QWidget()
        self.files_layout = QVBoxLayout(self.files_container)
        self.files_layout.setContentsMargins(0, 0, 0, 0)
        self.files_layout.setSpacing(4)
        # Small groups : rendu inline complet avec checkboxes (collapsed=False)
        # Big groups : preview 2 lignes, bouton "Voir/Modifier" pour le detail
        if self._is_small:
            self._render_files_inline()
        else:
            self._render_files(collapsed=True)
        main_row.addWidget(self.files_container, stretch=1)

        # Recap a droite
        recap_box = QVBoxLayout()
        recap_box.setSpacing(2)
        n_dup = len(group.items) - 1
        recap_top = QLabel(f"{len(group.items)} fichiers ({n_dup} doublon{'s' if n_dup > 1 else ''})")
        recap_top.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px;")
        recap_top.setAlignment(Qt.AlignmentFlag.AlignRight)
        recap_box.addWidget(recap_top)
        recap_bot = QLabel(f"Taille totale : {fmt_size(sum(a.size for a in group.items))}")
        recap_bot.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        recap_bot.setAlignment(Qt.AlignmentFlag.AlignRight)
        recap_box.addWidget(recap_bot)
        # Sous-info : pourcentage de match
        match_pct = self._compute_match_pct()
        kind_label = "EXACT" if group.kind == "exact" else "QUASI"
        match_lbl = QLabel(f"{kind_label} · {match_pct}%")
        if group.kind == "exact":
            match_lbl.setStyleSheet(
                f"color: white; background: {ACCENT}; padding: 1px 6px; "
                f"border-radius: 3px; font-size: 9px; font-weight: 700;"
            )
        else:
            match_lbl.setStyleSheet(
                f"color: black; background: {WARN}; padding: 1px 6px; "
                f"border-radius: 3px; font-size: 9px; font-weight: 700;"
            )
        match_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        recap_box.addWidget(match_lbl)
        main_row.addLayout(recap_box)

        # Boutons Voir/Modifier + expand : visible UNIQUEMENT si gros groupe
        # (small groups montrent deja tout inline avec checkboxes)
        if not self._is_small:
            self.see_btn = QPushButton(t("group.see_modify"))
            self.see_btn.setStyleSheet(
                f"background: {ACCENT}; color: white; padding: 6px 12px; "
                f"border-radius: 4px; font-weight: 700;"
            )
            self.see_btn.setToolTip("Voir tous les fichiers du groupe et choisir individuellement")
            self.see_btn.clicked.connect(self._open_selection_dialog)
            main_row.addWidget(self.see_btn)

            self.expand_btn = QPushButton("v")
            self.expand_btn.setFixedSize(28, 28)
            self.expand_btn.setProperty("role", "secondary")
            self.expand_btn.setToolTip("Voir les fichiers ici (mode rapide)")
            self.expand_btn.clicked.connect(self._toggle_expand)
            main_row.addWidget(self.expand_btn)
        else:
            # Pour les small groups, on n'a pas ces widgets mais on stub
            # pour eviter les AttributeError dans les methodes legacy
            self.see_btn = None  # type: ignore[assignment]
            self.expand_btn = None  # type: ignore[assignment]

        outer.addLayout(main_row)

    # ------------------------------------------------------------------
    def _compute_match_pct(self) -> int:
        if self.group.kind == "exact":
            return 100
        items = self.group.items
        if items and items[0].text_hash is not None:
            return 100
        if items and items[0].a_hash is not None:
            ref = items[0].a_hash
            distances = []
            for it in items[1:]:
                if it.a_hash is not None:
                    distances.append(bin(ref ^ it.a_hash).count("1"))
            if distances:
                avg = sum(distances) / len(distances)
                return int(round((64 - avg) / 64 * 100))
        return 95

    def _render_files_inline(self) -> None:
        """Rendu pour groupes <= INLINE_THRESHOLD : chaque fichier en ligne avec
        thumbnail + checkbox individuelle + nom + taille + chemin. Pas besoin
        de cliquer 'Voir/Modifier'."""
        self._clear_files()
        for i, asset in enumerate(self.group.items):
            row = QFrame()
            row.setStyleSheet(
                f"QFrame {{ background: transparent; border: none; }}"
            )
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)

            cb = QCheckBox()
            cb.setChecked(self._file_checks[i])
            cb.toggled.connect(lambda c, idx=i: self._on_file_toggled(idx, c))
            h.addWidget(cb)

            thumb = make_mini_thumbnail(asset.path, size=48)
            h.addWidget(thumb)

            text_col = QVBoxLayout()
            text_col.setSpacing(0)
            name_row = QHBoxLayout()
            name_row.setSpacing(6)
            name_lbl = QLabel(asset.path.name)
            name_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px;")
            name_lbl.setToolTip(asset.path.name)
            name_row.addWidget(name_lbl)
            if i == 0:
                tag = QLabel(t("group.keep"))
                tag.setStyleSheet(
                    f"background: {OK}; color: black; padding: 2px 7px; "
                    f"border-radius: 3px; font-size: 10px; font-weight: 700;"
                )
                tag.setToolTip(
                    "Version la plus volumineuse, generalement l'originale. "
                    "Recommande de la garder."
                )
                name_row.addWidget(tag)
            size_lbl = QLabel(fmt_size(asset.size))
            size_lbl.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
            name_row.addWidget(size_lbl)
            name_row.addStretch()
            text_col.addLayout(name_row)
            path_lbl = QLabel(str(asset.path))
            path_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 10px;")
            path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            path_lbl.setToolTip(str(asset.path))
            text_col.addWidget(path_lbl)
            h.addLayout(text_col, stretch=1)

            self.files_layout.addWidget(row)

    def _clear_files(self) -> None:
        while self.files_layout.count():
            it = self.files_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _render_files(self, collapsed: bool) -> None:
        """Affiche les fichiers. En mode collapsed, max 2 lignes preview."""
        self._clear_files()
        items = self.group.items
        n_show = 2 if collapsed else len(items)
        for i, asset in enumerate(items[:n_show]):
            line = QHBoxLayout()
            line.setSpacing(8)
            # Checkbox individuelle en mode expanded uniquement
            if not collapsed:
                cb = QCheckBox()
                cb.setChecked(self._file_checks[i])
                cb.toggled.connect(lambda c, idx=i: self._on_file_toggled(idx, c))
                # Premiere ligne = le + gros, suggestion = decoche
                line.addWidget(cb)

            # Nom + taille (1 ligne) + chemin (2eme ligne)
            text_col = QVBoxLayout()
            text_col.setSpacing(0)
            name_row = QHBoxLayout()
            name_row.setSpacing(8)
            name_lbl = QLabel(asset.path.name)
            name_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px;")
            name_row.addWidget(name_lbl)
            if i == 0 and not collapsed:
                tag = QLabel(t("group.keep"))
                tag.setStyleSheet(
                    f"background: {OK}; color: black; padding: 2px 7px; "
                    f"border-radius: 3px; font-size: 10px; font-weight: 700;"
                )
                tag.setToolTip("Version la plus volumineuse, generalement l'originale. Recommande de la garder.")
                name_row.addWidget(tag)
            size_lbl = QLabel(fmt_size(asset.size))
            size_lbl.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
            name_row.addWidget(size_lbl)
            name_row.addStretch()
            text_col.addLayout(name_row)
            path_lbl = QLabel(str(asset.path))
            path_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 10px;")
            path_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            path_lbl.setToolTip(str(asset.path))
            text_col.addWidget(path_lbl)
            line.addLayout(text_col, stretch=1)
            wrap = QWidget()
            wrap.setLayout(line)
            self.files_layout.addWidget(wrap)
        if collapsed and len(items) > 2:
            more = QLabel(f"+ {len(items) - 2} autre{'s' if len(items) - 2 > 1 else ''}...")
            more.setStyleSheet(f"color: {TEXT3}; font-size: 10px; font-style: italic;")
            self.files_layout.addWidget(more)

    def _toggle_expand(self) -> None:
        self._expanded = not self._expanded
        self.expand_btn.setText("^" if self._expanded else "v")
        self._render_files(collapsed=not self._expanded)

    def _on_master_toggled(self, checked: bool) -> None:
        # Master = "tous les fichiers sauf le + gros" si coche, sinon aucun
        for i in range(len(self._file_checks)):
            self._file_checks[i] = checked and i != 0
        # Rerender les checkboxes visuelles pour refleter le changement
        if self._is_small:
            self._render_files_inline()
        elif self._expanded:
            self._render_files(collapsed=False)
        self.selection_changed.emit()

    def _on_file_toggled(self, idx: int, checked: bool) -> None:
        # Protection : si l'index est hors-bornes (apres une suppression
        # ou un rerender en cours), on ignore le signal pour eviter crash.
        if 0 <= idx < len(self._file_checks):
            self._file_checks[idx] = checked
            self.selection_changed.emit()

    def _open_selection_dialog(self) -> None:
        """Ouvre le dialog 'Voir / Modifier la selection' avec tous les fichiers + checkbox individuelle."""
        from .dup_group_dialog import DupGroupContentsDialog
        dlg = DupGroupContentsDialog(self.group, self._file_checks, self)
        if dlg.exec() == 1:  # Accepted
            self._file_checks = dlg.checked_indices
            if self._expanded:
                self._render_files(collapsed=False)
            self.selection_changed.emit()

    # ------------------------------------------------------------------
    # API publique pour la vue parente
    # ------------------------------------------------------------------
    def is_master_checked(self) -> bool:
        return self.master_check.isChecked()

    def set_master_checked(self, checked: bool) -> None:
        self.master_check.blockSignals(True)
        self.master_check.setChecked(checked)
        self.master_check.blockSignals(False)
        # Re-applique la logique master
        self._on_master_toggled(checked)

    def checked_assets(self) -> list[Asset]:
        """Retourne les fichiers du groupe coches pour suppression."""
        return [a for a, c in zip(self.group.items, self._file_checks) if c]

    def uncheck_all_files(self) -> None:
        self._file_checks = [False] * len(self.group.items)
        self.master_check.blockSignals(True)
        self.master_check.setChecked(False)
        self.master_check.blockSignals(False)
        if self._is_small:
            self._render_files_inline()
        elif self._expanded:
            self._render_files(collapsed=False)
        self.selection_changed.emit()

    def check_all_but_first(self) -> None:
        self.set_master_checked(True)  # equivalent


# ---------------------------------------------------------------------------
# SortFileRow — 1 fichier a trier en ligne de tableau (mockup)
# ---------------------------------------------------------------------------
class SortFileRow(QFrame):
    """Ligne de tableau pour 1 fichier dans l'onglet Tri.
    Colonnes : [chk] [icon+name] [category badge] [destination folder] [edit btn]
    """

    selection_changed = pyqtSignal()
    edit_requested = pyqtSignal(object)
    focus_requested = pyqtSignal(object)  # quand l'user clique pour previewer

    def __init__(
        self,
        path: Path,
        category: str,
        folder: str,
        confidence: float,
        reason: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.path = path
        self.folder = folder
        self.category = category
        self.confidence = confidence
        self.reason = reason
        self._selected = False

        self.setObjectName("SortFileRow")
        self._apply_style()

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(10)

        # 1. Checkbox
        self.checkbox = QCheckBox()
        self.checkbox.toggled.connect(lambda _c: self.selection_changed.emit())
        row.addWidget(self.checkbox)

        # 2. Icon + nom
        icon = make_mini_thumbnail(path, size=36)
        row.addWidget(icon)
        name_lbl = QLabel(path.name)
        name_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 12px;")
        name_lbl.setToolTip(str(path))
        name_lbl.setMinimumWidth(220)
        row.addWidget(name_lbl, stretch=2)

        # 3. Badge categorie
        bg, fg = category_color(category)
        self.cat_badge = QLabel(category)
        self.cat_badge.setStyleSheet(
            f"background: {bg}; color: {fg}; padding: 4px 10px; "
            f"border-radius: 12px; font-size: 11px; font-weight: 700;"
        )
        self.cat_badge.setToolTip(f"Confiance : {int(confidence*100)}%  ·  Raison : {reason}")
        row.addWidget(self.cat_badge)

        # 4. Destination folder (editable inline)
        self.folder_input = QLineEdit(folder)
        self.folder_input.setStyleSheet(
            f"background: {CARD2}; color: {TEXT2}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 4px 8px; font-size: 11px;"
        )
        self.folder_input.setMinimumWidth(280)
        self.folder_input.editingFinished.connect(self._on_folder_text_changed)
        row.addWidget(self.folder_input, stretch=3)

        # 5. Bouton edit
        edit_btn = QPushButton("E")
        edit_btn.setFixedSize(28, 28)
        edit_btn.setProperty("role", "secondary")
        edit_btn.setToolTip("Choisir un dossier deja utilise")
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self))
        row.addWidget(edit_btn)

    def _apply_style(self) -> None:
        if self._selected:
            self.setStyleSheet(
                f"#SortFileRow {{ background: {CARD2}; border: 2px solid {ACCENT}; "
                f"border-radius: 6px; }}"
            )
        else:
            self.setStyleSheet(
                f"#SortFileRow {{ background: {CARD}; border: 1px solid {BORDER}; "
                f"border-radius: 6px; }}"
                f"#SortFileRow:hover {{ background: {CARD2}; }}"
            )

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        # Click sur la ligne = demande de preview a la vue parente
        self.focus_requested.emit(self)
        super().mousePressEvent(ev)

    def set_focused(self, focused: bool) -> None:
        self._selected = focused
        self._apply_style()

    def set_folder(self, folder: str) -> None:
        self.folder = folder
        self.folder_input.setText(folder)

    def set_known_folders(self, folders: list[str]) -> None:
        completer = QCompleter(folders, self.folder_input)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.folder_input.setCompleter(completer)

    def _on_folder_text_changed(self) -> None:
        new_val = self.folder_input.text().strip()
        if new_val != self.folder:
            self.folder = new_val

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, checked: bool) -> None:
        self.checkbox.blockSignals(True)
        self.checkbox.setChecked(checked)
        self.checkbox.blockSignals(False)

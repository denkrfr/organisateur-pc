"""Onglet Tri : analyse des fichiers et propose un dossier de classement.

UX (mockup) :
  - Split horizontal : tableau de fichiers a gauche + panneau Previsualisation
    a droite (image, metadata, mots-cles detectes, categorie, destination)
  - Stats cards en haut : nb analyses / nb categories / nb selectionnes
  - Lignes de table type SortFileRow avec : checkbox, icon+nom, badge categorie,
    dossier de destination editable, bouton edit
  - Bottom actions : Tout cocher / Tout decocher / Meme dossier pour selection
    / Deplacer la selection
"""

from __future__ import annotations
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFileDialog, QProgressBar, QMessageBox,
    QLineEdit, QCompleter, QDialog, QDialogButtonBox, QScrollArea, QFrame,
    QSplitter,
)

from core import sort, docs, exemplars, embeddings
from .styles import (
    fmt_size, ACCENT, ACCENT2, TEXT, TEXT2, TEXT3, CARD, CARD2, BORDER, OK,
)
from .result_cards import SortFileRow
from .detail_panel import DetailPanel
from .learning_dialog import LearningDialog


# ---------------------------------------------------------------------------
# Dialog "Deplacer dans dossier" — input libre + autocomplete
# ---------------------------------------------------------------------------
class FolderPickerDialog(QDialog):
    def __init__(
        self,
        suggestion: str,
        known_folders: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choisir un dossier")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Nom du dossier cible :"))

        self.input = QLineEdit(self)
        self.input.setText(suggestion)
        self.input.setPlaceholderText("Ex: Factures/2024/03 - Mars")
        completer = QCompleter(known_folders, self.input)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.input.setCompleter(completer)
        layout.addWidget(self.input)

        if known_folders:
            layout.addWidget(QLabel("Suggestions (deja utilises) :"))
            self.suggestions = QListWidget(self)
            for f in known_folders[:8]:
                QListWidgetItem(f, self.suggestions)
            self.suggestions.itemDoubleClicked.connect(
                lambda it: self.input.setText(it.text())
            )
            layout.addWidget(self.suggestions)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def folder_name(self) -> str:
        return self.input.text().strip()


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------
class AnalyzeWorker(QObject):
    progress = pyqtSignal(int, int, str)
    one_done = pyqtSignal(object, object)
    finished = pyqtSignal()
    failed = pyqtSignal(str)

    def __init__(self, files: list[Path]) -> None:
        super().__init__()
        self.files = files

    def run(self) -> None:
        try:
            total = len(self.files)
            for i, p in enumerate(self.files):
                suggestion = sort.propose_folder(p)
                self.one_done.emit(p, suggestion)
                self.progress.emit(i + 1, total, f"Analyse {i + 1} / {total}")
            self.finished.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class MoveWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int, int, list)

    def __init__(self, tasks: list[tuple[Path, Path, str]]) -> None:
        super().__init__()
        self.tasks = tasks

    def run(self) -> None:
        store = exemplars.ExemplarStore.get() if embeddings.embeddings_available() else None
        moved = 0
        learned = 0
        errors: list[str] = []
        total = len(self.tasks)
        for i, (src, dest, target_subfolder) in enumerate(self.tasks):
            try:
                if store is not None:
                    kind = docs.kind_of(src)
                    if kind == "image":
                        if store.add_image_exemplar(target_subfolder, src, defer_save=True):
                            learned += 1
                        try:
                            ocr = sort.ocr_text(src)
                            if ocr and len(ocr.strip()) >= 20:
                                store.add_text_exemplar(target_subfolder, ocr, defer_save=True)
                        except Exception:  # noqa: BLE001
                            pass
                    elif kind in ("pdf", "docx", "xlsx"):
                        try:
                            text = docs.extract_text(src, max_chars=5000)
                            if text and len(text.strip()) >= 20:
                                if store.add_text_exemplar(target_subfolder, text, defer_save=True):
                                    learned += 1
                        except Exception:  # noqa: BLE001
                            pass
                dest.parent.mkdir(parents=True, exist_ok=True)
                src.rename(dest)
                sort.remember_folder(target_subfolder)
                moved += 1
            except OSError as e:
                errors.append(f"{src.name} : {e}")
            self.progress.emit(i + 1, total)
        if store is not None:
            store.flush()
        self.finished.emit(moved, learned, errors)


# ---------------------------------------------------------------------------
# StatCard — petit indicateur (12 fichiers analyses, etc.)
# ---------------------------------------------------------------------------
class StatCard(QFrame):
    def __init__(self, icon: str, value: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px;"
        )
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 10, 14, 10)
        h.setSpacing(12)
        icon_lbl = QLabel(icon)
        icon_lbl.setStyleSheet(f"color: {ACCENT}; font-size: 22px; font-weight: 800;")
        h.addWidget(icon_lbl)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.value_lbl = QLabel(value)
        self.value_lbl.setStyleSheet(f"color: {TEXT}; font-size: 18px; font-weight: 700;")
        col.addWidget(self.value_lbl)
        self.label_lbl = QLabel(label)
        self.label_lbl.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        col.addWidget(self.label_lbl)
        h.addLayout(col)
        h.addStretch()

    def set_value(self, v: str) -> None:
        self.value_lbl.setText(v)


# ---------------------------------------------------------------------------
# Vue Tri principale
# ---------------------------------------------------------------------------
SUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".tiff", ".tif", ".gif",
    ".pdf", ".docx", ".xlsx",
}


class SortView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.rows: list[SortFileRow] = []
        self._worker: AnalyzeWorker | None = None
        self._thread: QThread | None = None
        self._move_worker: MoveWorker | None = None
        self._move_thread: QThread | None = None
        self._cards_to_move: list[SortFileRow] = []
        self._known_folders: list[str] = []
        self._dest_root: Optional[Path] = None
        self._focused_row: Optional[SortFileRow] = None
        self._build_ui()

    def _build_ui(self) -> None:
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        # === Panneau gauche ===
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(16, 16, 8, 16)
        left_layout.setSpacing(10)

        title = QLabel("Tri des fichiers")
        title.setStyleSheet(f"color: {TEXT}; font-size: 22px; font-weight: 800;")
        left_layout.addWidget(title)

        subtitle = QLabel(
            "L'application analyse vos fichiers et propose automatiquement une categorie ainsi qu'un dossier de destination."
        )
        subtitle.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        subtitle.setWordWrap(True)
        left_layout.addWidget(subtitle)

        # OCR warning si Tesseract absent
        if not sort._ocr_available():
            ocr_warn = QLabel(
                "OCR indisponible (Tesseract non installe). Le tri par texte dans les images est limite."
            )
            ocr_warn.setStyleSheet(
                "background: #2e2412; color: #ffd43b; padding: 6px; "
                "border: 1px solid #5a4612; border-radius: 4px; font-size: 11px;"
            )
            ocr_warn.setWordWrap(True)
            left_layout.addWidget(ocr_warn)

        # === Source row ===
        src_row = QHBoxLayout()
        src_lbl = QLabel("Source :")
        src_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600;")
        src_lbl.setFixedWidth(140)
        src_row.addWidget(src_lbl)
        self.src_input = QLineEdit()
        self.src_input.setReadOnly(True)
        self.src_input.setPlaceholderText("Choisir un dossier source...")
        self.src_input.setStyleSheet(
            f"background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 6px 10px;"
        )
        src_row.addWidget(self.src_input, stretch=1)
        choose_src = QPushButton("Choisir...")
        choose_src.setProperty("role", "secondary")
        choose_src.clicked.connect(self._choose_folder)
        src_row.addWidget(choose_src)
        left_layout.addLayout(src_row)

        # === Racine de classement row ===
        dest_row = QHBoxLayout()
        dest_lbl = QLabel("Racine de classement :")
        dest_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600;")
        dest_lbl.setFixedWidth(140)
        dest_row.addWidget(dest_lbl)
        self.dest_input = QLineEdit()
        self.dest_input.setReadOnly(True)
        self.dest_input.setPlaceholderText("(par defaut = meme dossier que source)")
        self.dest_input.setStyleSheet(
            f"background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 6px 10px;"
        )
        dest_row.addWidget(self.dest_input, stretch=1)
        change_dest = QPushButton("Changer...")
        change_dest.setProperty("role", "secondary")
        change_dest.clicked.connect(self._choose_dest)
        dest_row.addWidget(change_dest)
        left_layout.addLayout(dest_row)

        # === Action row ===
        action_row = QHBoxLayout()
        self.analyze_btn = QPushButton("Analyser")
        self.analyze_btn.clicked.connect(self._start_analyze)
        action_row.addWidget(self.analyze_btn)
        learn_btn = QPushButton("Apprentissage...")
        learn_btn.setProperty("role", "secondary")
        learn_btn.clicked.connect(self._open_learning_dialog)
        action_row.addWidget(learn_btn)
        reset_btn = QPushButton("Reinitialiser")
        reset_btn.setProperty("role", "secondary")
        reset_btn.clicked.connect(self._reset)
        action_row.addWidget(reset_btn)
        action_row.addStretch()
        preview_btn = QPushButton("Apercu des categories")
        preview_btn.setProperty("role", "secondary")
        preview_btn.clicked.connect(self._show_categories_overview)
        action_row.addWidget(preview_btn)
        left_layout.addLayout(action_row)

        # === Stats cards ===
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)
        self.stat_files = StatCard("=", "0", "fichiers analyses")
        self.stat_cats = StatCard("#", "0", "categories proposees")
        self.stat_sel = StatCard("v", "0", "selectionnes")
        stats_row.addWidget(self.stat_files)
        stats_row.addWidget(self.stat_cats)
        stats_row.addWidget(self.stat_sel)
        left_layout.addLayout(stats_row)

        # === Progress ===
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        left_layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        left_layout.addWidget(self.progress_bar)

        # === Header de la "table" ===
        header_row = QFrame()
        header_row.setStyleSheet(f"background: {CARD2}; border-radius: 4px;")
        h_lay = QHBoxLayout(header_row)
        h_lay.setContentsMargins(50, 8, 10, 8)  # offset checkbox
        h_lay.setSpacing(10)
        for txt, stretch, w in [("Fichier", 2, 256), ("Categorie proposee", 0, 120),
                                  ("Dossier de destination propose", 3, 280), ("", 0, 28)]:
            l = QLabel(txt)
            l.setStyleSheet(f"color: {TEXT2}; font-size: 11px; font-weight: 600;")
            if w:
                l.setMinimumWidth(w)
            h_lay.addWidget(l, stretch=stretch)
        left_layout.addWidget(header_row)

        # === Container des lignes (scroll) ===
        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(4)
        self._empty_lbl = QLabel("Choisis un dossier et lance l'analyse.")
        self._empty_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 12px;")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._rows_layout.addWidget(self._empty_lbl)
        self._rows_layout.addStretch()
        self.results_scroll.setWidget(self._rows_container)
        left_layout.addWidget(self.results_scroll, stretch=1)

        # === Bottom actions ===
        bottom = QHBoxLayout()
        check_all = QPushButton("Tout cocher")
        check_all.setProperty("role", "secondary")
        check_all.clicked.connect(self._check_all)
        bottom.addWidget(check_all)
        uncheck_all = QPushButton("Tout decocher")
        uncheck_all.setProperty("role", "secondary")
        uncheck_all.clicked.connect(self._uncheck_all)
        bottom.addWidget(uncheck_all)
        bulk_btn = QPushButton("Meme dossier pour la selection...")
        bulk_btn.setProperty("role", "secondary")
        bulk_btn.clicked.connect(self._bulk_edit_folder)
        bottom.addWidget(bulk_btn)
        bottom.addStretch()
        move_btn = QPushButton("Deplacer la selection")
        move_btn.clicked.connect(self._move_selection)
        bottom.addWidget(move_btn)
        left_layout.addLayout(bottom)

        splitter.addWidget(left)

        # === Panneau droit : DetailPanel ===
        self.detail_panel = DetailPanel()
        self.detail_panel.edit_category_requested.connect(self._edit_focused_row_folder)
        self.detail_panel.open_dest_requested.connect(self._open_focused_dest)
        right_wrap = QWidget()
        right_layout = QVBoxLayout(right_wrap)
        right_layout.setContentsMargins(8, 16, 16, 16)
        right_layout.addWidget(self.detail_panel)
        splitter.addWidget(right_wrap)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([900, 480])

    # ==================================================================
    # Source / dest
    # ==================================================================
    def _choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choisir le dossier source")
        if folder:
            self.src_input.setText(folder)

    def _choose_dest(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Racine de classement (les sous-dossiers seront crees ici)"
        )
        if folder:
            self._dest_root = Path(folder)
            self.dest_input.setText(folder)

    def _reset(self) -> None:
        ans = QMessageBox.question(
            self, "Reinitialiser",
            "Vider la liste actuelle et reinitialiser la source ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._clear_rows()
        self.src_input.setText("")
        self.dest_input.setText("")
        self._dest_root = None
        self.detail_panel.clear()
        self._update_stats()

    def _open_learning_dialog(self) -> None:
        dlg = LearningDialog(self)
        dlg.exec()

    def _show_categories_overview(self) -> None:
        """Affiche un dialog avec la liste des categories utilisees + nb fichiers."""
        from collections import Counter
        if not self.rows:
            QMessageBox.information(self, "Vide", "Aucun fichier analyse pour l'instant.")
            return
        cats = Counter(r.category for r in self.rows)
        text = "\n".join(f"  - {c} : {n} fichier(s)" for c, n in cats.most_common())
        QMessageBox.information(self, "Apercu des categories", f"Categories proposees :\n\n{text}")

    # ==================================================================
    # Analyze
    # ==================================================================
    def _start_analyze(self) -> None:
        src = self.src_input.text().strip()
        if not src:
            QMessageBox.information(self, "Pas de dossier", "Choisis un dossier source.")
            return
        files = [
            p for p in Path(src).rglob("*")
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
        ]
        if not files:
            QMessageBox.information(self, "Vide", "Aucun fichier supporte trouve.")
            return
        self._clear_rows()
        self._known_folders = [f for f, _ in sort.load_known_folders()]
        self._empty_lbl.setVisible(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(files))
        self.progress_label.setText("Analyse...")
        self.analyze_btn.setEnabled(False)

        self._thread = QThread(self)
        self._worker = AnalyzeWorker(files)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.one_done.connect(self._on_one_done)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_progress(self, c: int, t: int, label: str) -> None:
        self.progress_label.setText(label)
        self.progress_bar.setValue(c)

    def _on_one_done(self, path: Path, suggestion) -> None:
        row = SortFileRow(
            path=path,
            category=suggestion.category,
            folder=suggestion.suggested_folder,
            confidence=suggestion.confidence,
            reason=suggestion.reason,
        )
        row.set_known_folders(self._known_folders)
        row.selection_changed.connect(self._on_selection_changed)
        row.edit_requested.connect(self._edit_row_folder)
        row.focus_requested.connect(self._on_row_focused)
        self.rows.append(row)
        # Insert avant le stretch final
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)

    def _on_finished(self) -> None:
        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        self.progress_label.setText(f"Termine. {len(self.rows)} fichier(s) analyse(s).")
        self._update_stats()
        # Focus la 1ere ligne pour declencher le preview
        if self.rows:
            self._on_row_focused(self.rows[0])

    def _on_failed(self, msg: str) -> None:
        self.progress_bar.setVisible(False)
        self.analyze_btn.setEnabled(True)
        QMessageBox.critical(self, "Erreur", msg)

    # ==================================================================
    # Selection / focus
    # ==================================================================
    def _on_selection_changed(self) -> None:
        self._update_stats()

    def _check_all(self) -> None:
        for r in self.rows:
            r.set_checked(True)
        self._update_stats()

    def _uncheck_all(self) -> None:
        for r in self.rows:
            r.set_checked(False)
        self._update_stats()

    def _selected_rows(self) -> list[SortFileRow]:
        return [r for r in self.rows if r.is_checked()]

    def _on_row_focused(self, row: SortFileRow) -> None:
        for r in self.rows:
            r.set_focused(r is row)
        self._focused_row = row
        # Met a jour le DetailPanel a droite
        self.detail_panel.show_for(
            path=row.path,
            category=row.category,
            destination=row.folder,
            reason=row.reason,
            confidence=row.confidence,
        )

    # ==================================================================
    # Edition dossier
    # ==================================================================
    def _edit_row_folder(self, row: SortFileRow) -> None:
        known = [f for f, _ in sort.load_known_folders()]
        dlg = FolderPickerDialog(row.folder, known, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dlg.folder_name()
        if new_name:
            row.set_folder(new_name)
            if row is self._focused_row:
                self.detail_panel.show_for(
                    row.path, row.category, new_name, row.reason, row.confidence,
                )

    def _edit_focused_row_folder(self) -> None:
        if self._focused_row:
            self._edit_row_folder(self._focused_row)

    def _open_focused_dest(self) -> None:
        if not self._focused_row:
            return
        root = self._dest_root or Path(self.src_input.text().strip() or ".")
        target = root.joinpath(*self._focused_row.folder.replace("\\", "/").split("/"))
        if target.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))
        else:
            QMessageBox.information(
                self, "Dossier inexistant",
                f"Le dossier '{target}' n'existe pas encore. Il sera cree au deplacement.",
            )

    def _bulk_edit_folder(self) -> None:
        sel = self._selected_rows()
        if not sel:
            QMessageBox.information(self, "Selection vide", "Coche au moins une ligne.")
            return
        known = [f for f, _ in sort.load_known_folders()]
        dlg = FolderPickerDialog(sel[0].folder, known, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dlg.folder_name()
        if not new_name:
            return
        for r in sel:
            r.set_folder(new_name)
        if self._focused_row and self._focused_row in sel:
            self.detail_panel.show_for(
                self._focused_row.path, self._focused_row.category, new_name,
                self._focused_row.reason, self._focused_row.confidence,
            )

    # ==================================================================
    # Stats / clear
    # ==================================================================
    def _clear_rows(self) -> None:
        for r in self.rows:
            self._rows_layout.removeWidget(r)
            r.deleteLater()
        self.rows = []
        self._focused_row = None

    def _update_stats(self) -> None:
        n = len(self.rows)
        self.stat_files.set_value(str(n))
        cats = {r.category for r in self.rows}
        self.stat_cats.set_value(str(len(cats)))
        sel = sum(1 for r in self.rows if r.is_checked())
        self.stat_sel.set_value(str(sel))

    # ==================================================================
    # Move
    # ==================================================================
    def _move_selection(self) -> None:
        sel = self._selected_rows()
        if not sel:
            QMessageBox.information(self, "Selection vide", "Coche au moins une ligne.")
            return
        if self._dest_root is not None:
            root = self._dest_root
        else:
            src_text = self.src_input.text().strip()
            if not src_text:
                QMessageBox.warning(
                    self, "Pas de racine",
                    "Choisis une racine de classement ou un dossier source."
                )
                return
            root = Path(src_text)

        tasks: list[tuple[Path, Path, str]] = []
        rows_in_order: list[SortFileRow] = []
        for r in sel:
            r._on_folder_text_changed()  # pylint: disable=protected-access
            target_subfolder = r.folder
            if not target_subfolder:
                continue
            target_dir = root.joinpath(*target_subfolder.replace("\\", "/").split("/"))
            dest = target_dir / r.path.name
            if dest.exists():
                i = 1
                while True:
                    cand = target_dir / f"{r.path.stem}_{i}{r.path.suffix}"
                    if not cand.exists():
                        dest = cand
                        break
                    i += 1
            tasks.append((r.path, dest, target_subfolder))
            rows_in_order.append(r)
        if not tasks:
            QMessageBox.information(self, "Rien a faire", "Aucune ligne avec un dossier defini.")
            return

        self._cards_to_move = rows_in_order
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(tasks))
        self.progress_label.setText("Deplacement et apprentissage...")

        self._move_thread = QThread(self)
        self._move_worker = MoveWorker(tasks)
        self._move_worker.moveToThread(self._move_thread)
        self._move_thread.started.connect(self._move_worker.run)
        self._move_worker.progress.connect(lambda c, t: self.progress_bar.setValue(c))
        self._move_worker.finished.connect(self._on_move_done)
        self._move_worker.finished.connect(self._move_thread.quit)
        self._move_thread.finished.connect(self._cleanup_move_thread)
        self._move_thread.start()

    def _on_move_done(self, moved: int, learned: int, errors: list) -> None:
        for i in range(moved):
            if i < len(self._cards_to_move):
                row = self._cards_to_move[i]
                if row in self.rows:
                    self._rows_layout.removeWidget(row)
                    self.rows.remove(row)
                    if row is self._focused_row:
                        self._focused_row = None
                        self.detail_panel.clear()
                    row.deleteLater()
        self.progress_bar.setVisible(False)
        msg = f"Deplace : {moved} fichier(s)."
        if learned:
            msg += f"\nL'app a appris {learned} nouvel(s) exemple(s)."
        if errors:
            msg += "\n\nErreurs :\n" + "\n".join(errors[:10])
        QMessageBox.information(self, "Deplacement", msg)
        self._cards_to_move = []
        self._update_stats()
        if not self.rows:
            self._empty_lbl.setVisible(True)
            self._empty_lbl.setText("Tous les fichiers ont ete deplaces.")

    def _cleanup_move_thread(self) -> None:
        if self._move_worker is not None:
            self._move_worker.deleteLater()
            self._move_worker = None
        if self._move_thread is not None:
            self._move_thread.deleteLater()
            self._move_thread = None

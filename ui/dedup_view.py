"""Onglet Dedup : selection de dossiers, scan, resultats en grille de vignettes."""

from __future__ import annotations
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QListWidget,
    QListWidgetItem, QFileDialog, QProgressBar, QCheckBox, QMessageBox,
    QScrollArea, QFrame, QComboBox, QToolButton,
)

from send2trash import send2trash

from core import dedup
from core.i18n import t
from core.models import DupGroup, Asset
from .styles import fmt_size
from .result_cards import DupGroupRow


# ---------------------------------------------------------------------------
# Worker thread pour ne pas bloquer l'UI pendant le scan
# ---------------------------------------------------------------------------
class ScanWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)  # list[DupGroup]
    failed = pyqtSignal(str)
    cancelled = pyqtSignal()  # signal emis quand le scan est annule

    def __init__(self, folders: List[Path], include_p_hash: bool):
        super().__init__()
        self.folders = folders
        self.include_p_hash = include_p_hash
        import threading
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Demande l'annulation du scan. Le pipeline s'arretera a la prochaine
        check (granularite ~1 fichier ou ~1 groupe de verification)."""
        self._cancel_event.set()

    def run(self) -> None:
        try:
            groups = dedup.run_pipeline(
                self.folders,
                include_p_hash=self.include_p_hash,
                on_progress=lambda c, n, lbl: self.progress.emit(c, n, lbl),
                cancel_check=self._cancel_event.is_set,
            )
            self.finished.emit(groups)
        except dedup._Cancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


def _normalize_path_for_trash(p: Path) -> str:
    """Normalise un Path en str pour send2trash sur Windows.

    Probleme observe : sur certains paths (long, ou avec caracteres non-ASCII
    type coreen/chinois/etc.), pathlib produit une string avec le prefix
    extended-length '\\\\?\\' que send2trash ne gere pas bien. On le strip si
    present.

    Sans changement pour les paths normaux (la grande majorite).
    """
    s = str(p)
    # Le prefix extended-length Windows : \\?\C:\...
    # On le strip pour donner a send2trash le chemin classique C:\...
    if s.startswith("\\\\?\\"):
        s = s[4:]
    return s


def _send_to_trash_robust(p: Path) -> None:
    r"""send2trash mais avec fallback si la 1ere tentative echoue.

    Strategy :
      1. Strip le prefix \\?\ si present, essaie send2trash
      2. Si echoue ET que le path existe encore, retente avec le path resolu
         (resolve() = normalise les symlinks, remplace . et .., etc.)
      3. Si tout echoue, leve l'exception originale
    """
    normalized = _normalize_path_for_trash(p)
    try:
        send2trash(normalized)
        return
    except (OSError, Exception) as first_err:  # noqa: BLE001
        # Fallback : essaie avec path resolved si le fichier existe encore
        try:
            if p.exists():
                resolved = str(p.resolve())
                if resolved.startswith("\\\\?\\"):
                    resolved = resolved[4:]
                send2trash(resolved)
                return
        except Exception:  # noqa: BLE001
            pass
        # Tous les fallbacks ont echoue : relance l'erreur originale
        raise first_err


class TrashWorker(QObject):
    """Worker thread pour envoyer une liste de fichiers a la corbeille systeme.

    L'operation send2trash peut etre lente (surtout sur HDD ou si beaucoup de
    fichiers). On la fait dans un thread pour ne pas bloquer l'UI, et on emet
    un signal de progression pour la barre.

    On ne touche JAMAIS l'UI Qt depuis ce thread : on emet juste des signaux.
    """

    progress = pyqtSignal(int, int, str)  # done, total, current_file_name
    finished = pyqtSignal(int, list)      # moved_count, errors

    def __init__(self, paths: list[Path]):
        super().__init__()
        self.paths = list(paths)

    def run(self) -> None:
        moved = 0
        errors: list[str] = []
        total = len(self.paths)
        for i, p in enumerate(self.paths):
            try:
                self.progress.emit(i, total, p.name)
                _send_to_trash_robust(p)
                moved += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"{p.name}: {e}")
        self.progress.emit(total, total, "")
        self.finished.emit(moved, errors)


# ---------------------------------------------------------------------------
# Vue principale
# ---------------------------------------------------------------------------
class DedupView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.folders: List[Path] = []
        self.groups: List[DupGroup] = []
        self.group_rows: list[DupGroupRow] = []
        self._pending_groups: list = []
        self._rendered_count: int = 0
        self._more_btn = None
        self._worker: ScanWorker | None = None
        self._thread: QThread | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Ligne titre + bouton Retour (visible uniquement quand resultats affiches)
        title_row = QHBoxLayout()
        self.back_btn = QPushButton(t("common.back"))
        self.back_btn.setProperty("role", "secondary")
        self.back_btn.setToolTip(t("dedup.back_tip"))
        self.back_btn.clicked.connect(self._back_to_setup)
        self.back_btn.setVisible(False)
        title_row.addWidget(self.back_btn)
        title = QLabel(t("dedup.title"))
        title.setProperty("role", "title")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        subtitle = QLabel(t("dedup.subtitle"))
        subtitle.setProperty("role", "subtitle")
        layout.addWidget(subtitle)

        # --- Liste des dossiers a scanner ---
        folders_row = QHBoxLayout()
        self.folders_list = QListWidget()
        self.folders_list.setMaximumHeight(90)
        folders_row.addWidget(self.folders_list, stretch=1)

        folders_btns = QVBoxLayout()
        add_btn = QPushButton(t("dedup.add_folder"))
        add_btn.clicked.connect(self._add_folder)
        folders_btns.addWidget(add_btn)
        rm_btn = QPushButton(t("dedup.remove"))
        rm_btn.setProperty("role", "secondary")
        rm_btn.clicked.connect(self._remove_folder)
        folders_btns.addWidget(rm_btn)
        folders_btns.addStretch()
        folders_row.addLayout(folders_btns)
        layout.addLayout(folders_row)

        # --- Options + scan ---
        opt_row = QHBoxLayout()
        self.phash_cb = QCheckBox(t("dedup.include_phash"))
        self.phash_cb.setChecked(False)
        self.phash_cb.setToolTip(t("dedup.include_phash_tip"))
        opt_row.addWidget(self.phash_cb)
        opt_row.addStretch()
        self.scan_btn = QPushButton(t("dedup.scan"))
        self.scan_btn.clicked.connect(self._start_scan)
        opt_row.addWidget(self.scan_btn)
        self.cancel_btn = QPushButton(t("dedup.cancel_scan"))
        self.cancel_btn.setProperty("role", "danger")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self._cancel_scan)
        opt_row.addWidget(self.cancel_btn)
        layout.addLayout(opt_row)

        self.progress_label = QLabel("")
        self.progress_label.setProperty("role", "subtitle")
        layout.addWidget(self.progress_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # --- Bandeau Resultats + filtre ---
        from .styles import ACCENT, TEXT, TEXT2
        header_row = QHBoxLayout()
        results_title = QLabel(t("dedup.results"))
        results_title.setStyleSheet(f"color: {TEXT}; font-size: 15px; font-weight: 700;")
        header_row.addWidget(results_title)
        self.groups_badge = QLabel(t("dedup.groups_badge", n=0))
        self.groups_badge.setStyleSheet(
            f"background: {ACCENT}; color: white; padding: 2px 10px; "
            f"border-radius: 10px; font-size: 11px; font-weight: 700;"
        )
        header_row.addWidget(self.groups_badge)
        header_row.addStretch()
        filter_label = QLabel(t("dedup.filter"))
        filter_label.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        header_row.addWidget(filter_label)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([t("dedup.filter_all"), t("dedup.filter_exact"), t("dedup.filter_quasi")])
        self.filter_combo.currentIndexChanged.connect(self._apply_filter)
        header_row.addWidget(self.filter_combo)
        layout.addLayout(header_row)

        # --- Resultats en rangees (scroll vertical) ---
        self.results_scroll = QScrollArea()
        self.results_scroll.setWidgetResizable(True)
        self.results_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._results_container = QWidget()
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setContentsMargins(0, 0, 0, 0)
        self._results_layout.setSpacing(8)
        self._empty_lbl = QLabel(t("dedup.empty"))
        self._empty_lbl.setProperty("role", "subtitle")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._results_layout.addWidget(self._empty_lbl)
        self._results_layout.addStretch()
        self.results_scroll.setWidget(self._results_container)
        layout.addWidget(self.results_scroll, stretch=1)

        # --- Bottom bar ---
        bottom = QHBoxLayout()
        all_but_biggest_btn = QPushButton(t("dedup.bulk_keep_biggest"))
        all_but_biggest_btn.setProperty("role", "secondary")
        all_but_biggest_btn.clicked.connect(self._check_all_but_biggest_global)
        bottom.addWidget(all_but_biggest_btn)
        uncheck_btn = QPushButton(t("dedup.bulk_uncheck"))
        uncheck_btn.setProperty("role", "secondary")
        uncheck_btn.clicked.connect(self._uncheck_all_global)
        bottom.addWidget(uncheck_btn)
        bottom.addStretch()
        self.trash_btn = QPushButton(t("dedup.trash_btn"))
        self.trash_btn.setProperty("role", "danger")
        self.trash_btn.clicked.connect(self._send_checked_to_trash)
        bottom.addWidget(self.trash_btn)
        layout.addLayout(bottom)

        # --- Footer ---
        self.footer = QLabel(t("dedup.footer_zero"))
        self.footer.setProperty("role", "subtitle")
        layout.addWidget(self.footer)

    # ------------------------------------------------------------------
    # Selection de dossiers
    # ------------------------------------------------------------------
    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, t("dedup.pick_folder"))
        if not folder:
            return
        path = Path(folder)
        if path in self.folders:
            return
        self.folders.append(path)
        QListWidgetItem(str(path), self.folders_list)

    def _remove_folder(self) -> None:
        for it in self.folders_list.selectedItems():
            row = self.folders_list.row(it)
            self.folders_list.takeItem(row)
            del self.folders[row]

    # ------------------------------------------------------------------
    # Scan en thread
    # ------------------------------------------------------------------
    def _start_scan(self) -> None:
        if not self.folders:
            QMessageBox.information(self, t("dedup.no_folder_title"), t("dedup.no_folder_body"))
            return
        self.scan_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self._clear_results()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText(t("dedup.init"))

        self._thread = QThread(self)
        self._worker = ScanWorker(list(self.folders), self.phash_cb.isChecked())
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.cancelled.connect(self._on_cancelled)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.cancelled.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_thread)
        self._thread.start()

    def _cancel_scan(self) -> None:
        if self._worker is not None:
            self.cancel_btn.setEnabled(False)
            self.progress_label.setText(t("dedup.cancelling"))
            self._worker.cancel()

    def _on_cancelled(self) -> None:
        self.progress_bar.setVisible(False)
        self.progress_label.setText(t("dedup.cancelled"))
        self.scan_btn.setVisible(True)
        self.cancel_btn.setVisible(False)

    def _cleanup_thread(self) -> None:
        if self._worker:
            self._worker.deleteLater()
        if self._thread:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None

    def _on_progress(self, current: int, total: int, label: str) -> None:
        self.progress_label.setText(label)
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(current)
        else:
            self.progress_bar.setRange(0, 0)

    def _on_finished(self, groups: list) -> None:
        self.groups = groups
        self.progress_bar.setVisible(False)
        self.progress_label.setText(t("dedup.scan_done", n=len(groups)))
        self.scan_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        self._render_results(groups)
        # Affiche le bouton Retour si on a effectivement des resultats a montrer
        if groups:
            self.back_btn.setVisible(True)

    def _back_to_setup(self) -> None:
        """Efface les resultats et revient a l'etat initial de selection."""
        self._clear_results()
        self.groups = []
        self.groups_badge.setText(t("dedup.groups_badge", n=0))
        self._empty_lbl.setText(t("dedup.empty"))
        self._empty_lbl.setVisible(True)
        self.progress_label.setText("")
        self.footer.setText(t("dedup.footer_zero"))
        self.back_btn.setVisible(False)

    def _on_failed(self, error: str) -> None:
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.scan_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        QMessageBox.critical(self, t("dedup.scan_error_title"), error)

    # ------------------------------------------------------------------
    # Rendu resultats (DupGroupRow)
    # ------------------------------------------------------------------
    PAGE_SIZE = 50  # Anti-crash : limite le nb de groupes rendus en RAM

    def _clear_results(self) -> None:
        for row in self.group_rows:
            self._results_layout.removeWidget(row)
            row.deleteLater()
        self.group_rows = []
        # Retire aussi un eventuel bouton "Afficher plus"
        if hasattr(self, "_more_btn") and self._more_btn is not None:
            self._results_layout.removeWidget(self._more_btn)
            self._more_btn.deleteLater()
            self._more_btn = None
        self._empty_lbl.setVisible(True)
        self._pending_groups: list = []
        self._rendered_count = 0

    def _render_results(self, groups: list[DupGroup]) -> None:
        self._clear_results()
        if not groups:
            self._empty_lbl.setText(t("dedup.no_dup_found"))
            self._update_footer()
            self.groups_badge.setText(t("dedup.groups_badge", n=0))
            return
        self._empty_lbl.setVisible(False)
        self._pending_groups = list(groups)
        self._rendered_count = 0
        self._render_next_page()
        self.groups_badge.setText(t("dedup.groups_badge", n=len(groups)))
        self._apply_filter()
        self._update_footer()

    def _render_next_page(self) -> None:
        """Rend les PAGE_SIZE prochains groupes pour eviter d'exploser la RAM
        sur les gros scans (1000+ groupes)."""
        # Retire le bouton "Afficher plus" eventuel
        if hasattr(self, "_more_btn") and self._more_btn is not None:
            self._results_layout.removeWidget(self._more_btn)
            self._more_btn.deleteLater()
            self._more_btn = None
        # Rend les prochains groupes
        end = min(self._rendered_count + self.PAGE_SIZE, len(self._pending_groups))
        for i in range(self._rendered_count, end):
            g = self._pending_groups[i]
            row = DupGroupRow(g, index=i + 1)
            row.selection_changed.connect(self._update_footer)
            self.group_rows.append(row)
            self._results_layout.insertWidget(self._results_layout.count() - 1, row)
        self._rendered_count = end
        # Si reste, ajoute un bouton "Afficher plus"
        remaining = len(self._pending_groups) - self._rendered_count
        if remaining > 0:
            self._more_btn = QPushButton(
                t("dedup.show_more", n=min(self.PAGE_SIZE, remaining), rest=remaining)
            )
            self._more_btn.setProperty("role", "secondary")
            self._more_btn.clicked.connect(self._render_next_page)
            self._results_layout.insertWidget(self._results_layout.count() - 1, self._more_btn)
        else:
            self._more_btn = None

    # ------------------------------------------------------------------
    # Filtre
    # ------------------------------------------------------------------
    def _apply_filter(self) -> None:
        idx = self.filter_combo.currentIndex() if hasattr(self, "filter_combo") else 0
        for row in self.group_rows:
            if idx == 1 and row.group.kind != "exact":
                row.setVisible(False)
            elif idx == 2 and row.group.kind != "quasi":
                row.setVisible(False)
            else:
                row.setVisible(True)

    # ------------------------------------------------------------------
    # Actions globales
    # ------------------------------------------------------------------
    def _check_all_but_biggest_global(self) -> None:
        for row in self.group_rows:
            row.set_master_checked(True)
        self._update_footer()

    def _uncheck_all_global(self) -> None:
        for row in self.group_rows:
            row.uncheck_all_files()
        self._update_footer()

    def _all_checked(self) -> list[tuple[DupGroupRow, Asset]]:
        out: list[tuple[DupGroupRow, Asset]] = []
        for row in self.group_rows:
            for a in row.checked_assets():
                out.append((row, a))
        return out

    def _update_footer(self) -> None:
        if not self.group_rows:
            self.footer.setText(t("dedup.footer_zero"))
            return
        checked = self._all_checked()
        n_groups = len(self.group_rows)
        if not checked:
            total = sum(g.total_recoverable for g in self.groups)
            self.footer.setText(
                t("dedup.footer_groups", n=n_groups, size=fmt_size(total))
            )
            return
        bytes_sel = sum(a.size for _, a in checked)
        self.footer.setText(
            t("dedup.footer_checked", n=len(checked), size=fmt_size(bytes_sel))
        )

    # ------------------------------------------------------------------
    # Action corbeille (via worker thread + retour accueil quand fini)
    # ------------------------------------------------------------------
    def _send_checked_to_trash(self) -> None:
        checked = self._all_checked()
        if not checked:
            QMessageBox.information(self, t("common.empty"), t("dedup.nothing_to_delete"))
            return
        bytes_total = sum(a.size for _, a in checked)
        ans = QMessageBox.question(
            self,
            t("dedup.trash_confirm_title"),
            t("dedup.trash_confirm_body", n=len(checked), size=fmt_size(bytes_total)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        # Worker thread : on ne fait JAMAIS d'UI update au milieu de la boucle.
        # Quand le worker emet finished, on affiche le message + retour accueil.
        paths = [a.path for _, a in checked]

        # Desactive tous les boutons d'action pendant l'operation
        self.trash_btn.setEnabled(False)
        self.scan_btn.setEnabled(False)

        # Affiche la barre de progression
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(paths))
        self.progress_bar.setValue(0)
        self.progress_label.setText(t("dedup.trash_progress", done=0, total=len(paths)))

        # Demarre le worker
        self._trash_thread = QThread()
        self._trash_worker = TrashWorker(paths)
        self._trash_worker.moveToThread(self._trash_thread)
        self._trash_thread.started.connect(self._trash_worker.run)
        self._trash_worker.progress.connect(self._on_trash_progress)
        self._trash_worker.finished.connect(self._on_trash_finished)
        self._trash_worker.finished.connect(self._trash_thread.quit)
        self._trash_worker.finished.connect(self._trash_worker.deleteLater)
        self._trash_thread.finished.connect(self._trash_thread.deleteLater)
        self._trash_thread.start()

    def _on_trash_progress(self, done: int, total: int, current: str) -> None:
        self.progress_bar.setValue(done)
        if current:
            self.progress_label.setText(t("dedup.trash_progress_file", done=done, total=total, file=current))
        else:
            self.progress_label.setText(t("dedup.trash_progress", done=done, total=total))

    def _on_trash_finished(self, moved: int, errors: list) -> None:
        # On masque la barre + reactive les boutons AVANT de toucher les widgets
        # de resultats (le _back_to_setup les detruit, et on veut etre sur que
        # plus aucun signal n'arrive a un widget mort).
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.trash_btn.setEnabled(True)
        self.scan_btn.setEnabled(True)

        # Message de confirmation
        msg = t("dedup.trash_done_full", n=moved)
        if errors:
            msg += t("dedup.trash_errors", n=len(errors)) + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n... ({len(errors) - 10})"
        QMessageBox.information(self, t("common.done"), msg)

        # Retour ecran d'accueil (efface tous les groupes affiches sans toucher
        # aux fichiers sur disque). C'est l'approche la plus robuste : on ne
        # touche pas a l'UI en place, on rebuilde un etat propre.
        self._back_to_setup()

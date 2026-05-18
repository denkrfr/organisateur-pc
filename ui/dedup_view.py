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
                on_progress=lambda c, t, lbl: self.progress.emit(c, t, lbl),
                cancel_check=self._cancel_event.is_set,
            )
            self.finished.emit(groups)
        except dedup._Cancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


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
        self.back_btn = QPushButton("← Retour")
        self.back_btn.setProperty("role", "secondary")
        self.back_btn.setToolTip("Effacer les resultats et revenir a la selection de dossiers")
        self.back_btn.clicked.connect(self._back_to_setup)
        self.back_btn.setVisible(False)
        title_row.addWidget(self.back_btn)
        title = QLabel("Detection de doublons")
        title.setProperty("role", "title")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        subtitle = QLabel(
            "Scanne les dossiers pour les doublons exacts et quasi-doublons "
            "(images + PDF/Word/Excel). 100% local."
        )
        subtitle.setProperty("role", "subtitle")
        layout.addWidget(subtitle)

        # --- Liste des dossiers a scanner ---
        folders_row = QHBoxLayout()
        self.folders_list = QListWidget()
        self.folders_list.setMaximumHeight(90)
        folders_row.addWidget(self.folders_list, stretch=1)

        folders_btns = QVBoxLayout()
        add_btn = QPushButton("Ajouter dossier")
        add_btn.clicked.connect(self._add_folder)
        folders_btns.addWidget(add_btn)
        rm_btn = QPushButton("Retirer")
        rm_btn.setProperty("role", "secondary")
        rm_btn.clicked.connect(self._remove_folder)
        folders_btns.addWidget(rm_btn)
        folders_btns.addStretch()
        folders_row.addLayout(folders_btns)
        layout.addLayout(folders_row)

        # --- Options + scan ---
        opt_row = QHBoxLayout()
        self.phash_cb = QCheckBox("Detecter aussi les quasi-doublons (recompressions, exports HEIC/JPG)")
        self.phash_cb.setChecked(False)
        self.phash_cb.setToolTip(
            "Decoche par defaut : detection visuelle via aHash (8x8 grayscale) qui "
            "peut generer des faux positifs (photos visuellement proches mais pas "
            "vraiment doublons). A activer surtout pour retrouver des "
            "compressions WhatsApp / exports HEIC->JPG de la meme photo originale."
        )
        opt_row.addWidget(self.phash_cb)
        opt_row.addStretch()
        self.scan_btn = QPushButton("Scanner")
        self.scan_btn.clicked.connect(self._start_scan)
        opt_row.addWidget(self.scan_btn)
        self.cancel_btn = QPushButton("Annuler")
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
        results_title = QLabel("Resultats du scan")
        results_title.setStyleSheet(f"color: {TEXT}; font-size: 15px; font-weight: 700;")
        header_row.addWidget(results_title)
        self.groups_badge = QLabel("0 groupes")
        self.groups_badge.setStyleSheet(
            f"background: {ACCENT}; color: white; padding: 2px 10px; "
            f"border-radius: 10px; font-size: 11px; font-weight: 700;"
        )
        header_row.addWidget(self.groups_badge)
        header_row.addStretch()
        filter_label = QLabel("Afficher :")
        filter_label.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        header_row.addWidget(filter_label)
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["Tous les groupes", "Exacts uniquement", "Quasi uniquement"])
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
        self._empty_lbl = QLabel("Lance un scan pour voir les doublons.")
        self._empty_lbl.setProperty("role", "subtitle")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._results_layout.addWidget(self._empty_lbl)
        self._results_layout.addStretch()
        self.results_scroll.setWidget(self._results_container)
        layout.addWidget(self.results_scroll, stretch=1)

        # --- Bottom bar ---
        bottom = QHBoxLayout()
        all_but_biggest_btn = QPushButton("Tous groupes : garder la version la plus volumineuse")
        all_but_biggest_btn.setProperty("role", "secondary")
        all_but_biggest_btn.clicked.connect(self._check_all_but_biggest_global)
        bottom.addWidget(all_but_biggest_btn)
        uncheck_btn = QPushButton("Tout decocher")
        uncheck_btn.setProperty("role", "secondary")
        uncheck_btn.clicked.connect(self._uncheck_all_global)
        bottom.addWidget(uncheck_btn)
        bottom.addStretch()
        self.trash_btn = QPushButton("Envoyer a la corbeille systeme")
        self.trash_btn.setProperty("role", "danger")
        self.trash_btn.clicked.connect(self._send_checked_to_trash)
        bottom.addWidget(self.trash_btn)
        layout.addLayout(bottom)

        # --- Footer ---
        self.footer = QLabel("0 groupe trouve")
        self.footer.setProperty("role", "subtitle")
        layout.addWidget(self.footer)

    # ------------------------------------------------------------------
    # Selection de dossiers
    # ------------------------------------------------------------------
    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choisir un dossier a scanner")
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
            QMessageBox.information(self, "Pas de dossier", "Ajoute au moins un dossier a scanner.")
            return
        self.scan_btn.setVisible(False)
        self.cancel_btn.setVisible(True)
        self.cancel_btn.setEnabled(True)
        self._clear_results()
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.progress_label.setText("Initialisation...")

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
            self.progress_label.setText("Annulation en cours...")
            self._worker.cancel()

    def _on_cancelled(self) -> None:
        self.progress_bar.setVisible(False)
        self.progress_label.setText("Scan annule.")
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
        self.progress_label.setText(f"Termine. {len(groups)} groupe(s) trouve(s).")
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
        self.groups_badge.setText("0 groupes")
        self._empty_lbl.setText("Lance un scan pour voir les doublons.")
        self._empty_lbl.setVisible(True)
        self.progress_label.setText("")
        self.footer.setText("0 groupe trouve")
        self.back_btn.setVisible(False)

    def _on_failed(self, error: str) -> None:
        self.progress_bar.setVisible(False)
        self.progress_label.setText("")
        self.scan_btn.setVisible(True)
        self.cancel_btn.setVisible(False)
        QMessageBox.critical(self, "Erreur de scan", error)

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
            self._empty_lbl.setText("Aucun doublon trouve.")
            self._update_footer()
            self.groups_badge.setText("0 groupes")
            return
        self._empty_lbl.setVisible(False)
        self._pending_groups = list(groups)
        self._rendered_count = 0
        self._render_next_page()
        self.groups_badge.setText(f"{len(groups)} groupes")
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
            self._more_btn = QPushButton(f"Afficher {min(self.PAGE_SIZE, remaining)} de plus ({remaining} restants)")
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
            self.footer.setText("0 groupe trouve")
            return
        checked = self._all_checked()
        n_groups = len(self.group_rows)
        if not checked:
            total = sum(g.total_recoverable for g in self.groups)
            self.footer.setText(
                f"{n_groups} groupe(s) trouves — {fmt_size(total)} recuperables au total"
            )
            return
        bytes_sel = sum(a.size for _, a in checked)
        self.footer.setText(
            f"{len(checked)} fichier(s) coche(s) — {fmt_size(bytes_sel)} a liberer"
        )

    # ------------------------------------------------------------------
    # Action corbeille
    # ------------------------------------------------------------------
    def _send_checked_to_trash(self) -> None:
        checked = self._all_checked()
        if not checked:
            QMessageBox.information(self, "Rien a supprimer", "Coche au moins un fichier.")
            return
        bytes_total = sum(a.size for _, a in checked)
        ans = QMessageBox.question(
            self,
            "Envoyer a la corbeille ?",
            f"{len(checked)} fichier(s) seront envoyes a la corbeille systeme.\n\n"
            f"{fmt_size(bytes_total)} seront liberes.\n\n"
            "Tu pourras les recuperer depuis la corbeille Windows tant qu'elle "
            "n'est pas vide.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        # === Phase 1 : send2trash (operation systeme) ===
        moved = 0
        errors: list[str] = []
        removed_per_row: dict[object, list[Asset]] = {}
        for row, asset in checked:
            try:
                send2trash(str(asset.path))
                removed_per_row.setdefault(row, []).append(asset)
                moved += 1
            except Exception as e:  # noqa: BLE001 — OSError ou autre
                errors.append(f"{asset.path.name}: {e}")

        # === Phase 2 : mise a jour de l'UI (en mode safe) ===
        # On bloque tous les signaux pendant la manipulation pour eviter qu'une
        # checkbox emette un toggled sur un widget en cours de destruction.
        try:
            for row, removed_assets in removed_per_row.items():
                # Retire les assets supprimes des items du groupe
                for a in removed_assets:
                    if a in row.group.items:
                        row.group.items.remove(a)
                # Reset les checks pour aligner avec la nouvelle liste d'items
                row._file_checks = [False] * len(row.group.items)
                # Rerender les fichiers du row si > 1 item restant
                if len(row.group.items) >= 2:
                    if row._is_small:
                        row._render_files_inline()
                    elif row._expanded:
                        row._render_files(collapsed=False)
                    else:
                        row._render_files(collapsed=True)

            # Retire les groupes qui n'ont plus que 0 ou 1 fichier
            for row in list(self.group_rows):
                if len(row.group.items) < 2:
                    try:
                        self._results_layout.removeWidget(row)
                        row.setParent(None)  # detache avant deleteLater
                        row.deleteLater()
                    except Exception:  # noqa: BLE001
                        pass
                    self.group_rows.remove(row)
            self.groups_badge.setText(f"{len(self.group_rows)} groupes")
            self._update_footer()
        except Exception as e:  # noqa: BLE001 — proteger l'UI d'un crash total
            QMessageBox.warning(
                self, "Suppression OK mais probleme UI",
                f"Les fichiers ont ete envoyes a la corbeille mais l'UI a eu un "
                f"souci : {e}. Tu peux relancer un scan pour rafraichir.",
            )
            return

        # === Phase 3 : feedback final ===
        msg = f"{moved} fichier(s) envoyes a la corbeille."
        if errors:
            msg += "\n\nErreurs :\n" + "\n".join(errors[:10])
        QMessageBox.information(self, "Termine", msg)
        self._update_footer()
        if not self.group_cards:
            self._empty_lbl.setVisible(True)
            self._empty_lbl.setText("Aucun doublon restant.")

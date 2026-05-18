"""Dialog d'apprentissage manuel + import automatique depuis arborescence
existante (la solution vraiment utile : prend les fichiers deja organises
de l'user comme exemplars du store).
"""

from __future__ import annotations
import random
from pathlib import Path
from typing import List

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QFileDialog, QMessageBox, QInputDialog, QProgressBar, QWidget,
    QDialogButtonBox,
)

from core import exemplars, docs, embeddings, sort
from .styles import TEXT, TEXT2, ACCENT, OK


SUPPORTED_FOR_LEARN = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".tiff", ".tif", ".gif",
    ".pdf", ".docx", ".xlsx",
}

# Combien d'exemples max prendre par sous-dossier lors de l'import auto
MAX_EXEMPLARS_PER_FOLDER_IMPORT = 8


# ---------------------------------------------------------------------------
# Worker : import auto depuis l'arborescence existante de l'user
# ---------------------------------------------------------------------------
class ImportFromTreeWorker(QObject):
    """Scanne un dossier racine, et pour chaque sous-dossier non vide,
    prend N fichiers comme exemplars. C'est la maniere la plus efficace
    d'amorcer le store : on utilise le tri DEJA fait par l'user."""

    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(int, int)  # (nb_folders_done, nb_exemplars_added)
    failed = pyqtSignal(str)

    def __init__(self, root: Path, max_per_folder: int = MAX_EXEMPLARS_PER_FOLDER_IMPORT) -> None:
        super().__init__()
        self.root = root
        self.max_per_folder = max_per_folder

    def run(self) -> None:
        try:
            store = exemplars.ExemplarStore.get()
            # 1. Liste tous les sous-dossiers (1 a 3 niveaux)
            folders: dict[str, list[Path]] = {}
            for path in self.root.rglob("*"):
                if not path.is_file():
                    continue
                if path.suffix.lower() not in SUPPORTED_FOR_LEARN:
                    continue
                # Calcule le nom relatif du dossier parent
                try:
                    rel_parent = path.parent.relative_to(self.root)
                except ValueError:
                    continue
                if str(rel_parent) == ".":
                    continue  # fichiers a la racine, on saute
                folder_name = str(rel_parent).replace("\\", "/")
                folders.setdefault(folder_name, []).append(path)

            if not folders:
                self.finished.emit(0, 0)
                return

            total = sum(min(len(files), self.max_per_folder) for files in folders.values())
            done = 0
            added = 0
            for folder_name, files in folders.items():
                # Echantillonnage : si > max, prend N aleatoirement (plus de variete)
                if len(files) > self.max_per_folder:
                    sample = random.sample(files, self.max_per_folder)
                else:
                    sample = files

                for f in sample:
                    kind = docs.kind_of(f)
                    if kind == "image":
                        if store.add_image_exemplar(folder_name, f, defer_save=True):
                            added += 1
                        # OCR text si dispo
                        try:
                            ocr = sort.ocr_text(f)
                            if ocr and len(ocr.strip()) >= 20:
                                store.add_text_exemplar(folder_name, ocr, defer_save=True)
                        except Exception:  # noqa: BLE001
                            pass
                    elif kind in ("pdf", "docx", "xlsx"):
                        try:
                            text = docs.extract_text(f, max_chars=5000)
                            if text and len(text.strip()) >= 20:
                                if store.add_text_exemplar(folder_name, text, defer_save=True):
                                    added += 1
                        except Exception:  # noqa: BLE001
                            pass
                    done += 1
                    self.progress.emit(done, total, f"{folder_name} : {f.name}")
                # Memorise aussi le dossier dans sort_folders pour autocomplete
                sort.remember_folder(folder_name)

            store.flush()
            self.finished.emit(len(folders), added)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# Worker : calcule les embeddings en background
# ---------------------------------------------------------------------------
class LearnWorker(QObject):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int)  # nb appris
    failed = pyqtSignal(str)

    def __init__(self, folder: str, paths: list[Path]) -> None:
        super().__init__()
        self.folder = folder
        self.paths = paths

    def run(self) -> None:
        try:
            store = exemplars.ExemplarStore.get()
            ok = 0
            total = len(self.paths)
            for i, p in enumerate(self.paths):
                kind = docs.kind_of(p)
                if kind == "image":
                    if store.add_image_exemplar(self.folder, p):
                        ok += 1
                    # Apprend aussi le texte OCR si dispo
                    try:
                        text = sort.ocr_text(p)
                        if text and len(text.strip()) >= 20:
                            store.add_text_exemplar(self.folder, text)
                    except Exception:  # noqa: BLE001
                        pass
                elif kind in ("pdf", "docx", "xlsx"):
                    try:
                        text = docs.extract_text(p, max_chars=5000)
                        if text and len(text.strip()) >= 20:
                            if store.add_text_exemplar(self.folder, text):
                                ok += 1
                    except Exception:  # noqa: BLE001
                        pass
                self.progress.emit(i + 1, total)
            self.finished.emit(ok)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


# ---------------------------------------------------------------------------
# Dialog principal
# ---------------------------------------------------------------------------
class LearningDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Apprentissage manuel")
        self.setMinimumSize(640, 500)
        self._worker: LearnWorker | None = None
        self._thread: QThread | None = None
        self._build_ui()
        self._refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Apprentissage manuel")
        title.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: 700;")
        layout.addWidget(title)

        info = QLabel(
            "Le plus efficace : utilise <b>Importer depuis dossier existant</b> "
            "pour amorcer automatiquement le store avec tes fichiers DEJA tries. "
            "L'app va scanner les sous-dossiers et apprendre de leur contenu.\n\n"
            "Sinon : selectionne un dossier dans la liste et ajoute des exemples "
            "manuellement. Tout est calcule localement."
        )
        info.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(info)

        # Bouton principal : import auto
        import_row = QHBoxLayout()
        self.import_btn = QPushButton("Importer depuis dossier existant...")
        self.import_btn.setStyleSheet(
            f"background: {ACCENT}; color: white; padding: 8px 16px; "
            f"border-radius: 4px; font-weight: 700;"
        )
        self.import_btn.clicked.connect(self._import_from_tree)
        import_row.addWidget(self.import_btn)
        import_row.addStretch()
        layout.addLayout(import_row)

        if not embeddings.embeddings_available():
            warn = QLabel(
                "⚠ Modeles d'embeddings non disponibles. L'apprentissage semantique est desactive."
            )
            warn.setStyleSheet("color: #ff6b6b; padding: 6px;")
            warn.setWordWrap(True)
            layout.addWidget(warn)

        # Liste des dossiers
        layout.addWidget(QLabel("Dossiers connus :"))
        self.folders_list = QListWidget()
        self.folders_list.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.folders_list, stretch=1)

        # Action row
        actions = QHBoxLayout()
        self.new_btn = QPushButton("+ Nouveau dossier...")
        self.new_btn.setProperty("role", "secondary")
        self.new_btn.clicked.connect(self._new_folder)
        actions.addWidget(self.new_btn)
        self.add_btn = QPushButton("Ajouter des exemples...")
        self.add_btn.clicked.connect(self._add_examples)
        self.add_btn.setEnabled(False)
        actions.addWidget(self.add_btn)
        self.clear_btn = QPushButton("Effacer les exemples")
        self.clear_btn.setProperty("role", "danger")
        self.clear_btn.clicked.connect(self._clear_folder_examples)
        self.clear_btn.setEnabled(False)
        actions.addWidget(self.clear_btn)
        actions.addStretch()
        layout.addLayout(actions)

        # Progress
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Close
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    def _import_from_tree(self) -> None:
        """Scanne un dossier racine et amorce automatiquement le store avec
        les sous-dossiers et leurs fichiers existants."""
        root_str = QFileDialog.getExistingDirectory(
            self,
            "Choisir la racine de ton arborescence deja triee",
        )
        if not root_str:
            return
        root = Path(root_str)
        # Compte rapidement les sous-dossiers pour confirmer
        subfolders = [p for p in root.iterdir() if p.is_dir()]
        if not subfolders:
            QMessageBox.information(
                self, "Vide",
                f"Aucun sous-dossier trouve dans {root}.\n\n"
                "Choisis ta RACINE qui contient des sous-dossiers thematiques "
                "(skyvision/, tomntoms/, etc.)"
            )
            return
        ans = QMessageBox.question(
            self,
            "Confirmer l'import",
            f"Vais scanner {root} et apprendre depuis {len(subfolders)} sous-dossier(s) "
            f"(jusqu'a {MAX_EXEMPLARS_PER_FOLDER_IMPORT} fichiers par sous-dossier).\n\n"
            f"Cela peut prendre quelques minutes selon le nombre de fichiers.\n\n"
            f"Continuer ?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        self.import_btn.setEnabled(False)
        self.new_btn.setEnabled(False)
        self.add_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, 0)  # indeterminate au debut
        self.progress.setFormat("Scan en cours...")

        self._thread = QThread(self)
        self._worker = ImportFromTreeWorker(root)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_import_progress)
        self._worker.finished.connect(self._on_import_done)
        self._worker.failed.connect(self._on_import_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_import_progress(self, done: int, total: int, current: str) -> None:
        if self.progress.maximum() == 0 and total > 0:
            self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.progress.setFormat(f"{done}/{total}  -  {current[:60]}")

    def _on_import_done(self, n_folders: int, n_exemplars: int) -> None:
        self.progress.setVisible(False)
        self.import_btn.setEnabled(True)
        self.new_btn.setEnabled(True)
        self._update_buttons()
        QMessageBox.information(
            self, "Import termine",
            f"Apprentissage termine :\n"
            f"  - {n_folders} dossier(s) appris\n"
            f"  - {n_exemplars} exemple(s) ajoute(s)\n\n"
            "Au prochain tri, l'app reconnaitra les fichiers similaires."
        )
        self._refresh()

    def _on_import_failed(self, msg: str) -> None:
        self.progress.setVisible(False)
        self.import_btn.setEnabled(True)
        self.new_btn.setEnabled(True)
        self._update_buttons()
        QMessageBox.critical(self, "Erreur", msg)

    # ------------------------------------------------------------------
    def _refresh(self) -> None:
        self.folders_list.clear()
        # Reunis : dossiers connus via deplacement + dossiers avec exemplars
        known = {f for f, _ in sort.load_known_folders()}
        store = exemplars.ExemplarStore.get() if embeddings.embeddings_available() else None
        if store is not None:
            known.update(store.known_folders())
        for folder in sorted(known):
            ni, nt = (0, 0)
            if store is not None:
                ni, nt = store.exemplar_count(folder)
            item = QListWidgetItem()
            item.setText(f"  {folder}    [ {ni} images  ·  {nt} textes ]")
            item.setData(Qt.ItemDataRole.UserRole, folder)
            self.folders_list.addItem(item)

    def _selected_folder(self) -> str | None:
        items = self.folders_list.selectedItems()
        if not items:
            return None
        return items[0].data(Qt.ItemDataRole.UserRole)

    def _update_buttons(self) -> None:
        has = self._selected_folder() is not None
        self.add_btn.setEnabled(has and embeddings.embeddings_available())
        self.clear_btn.setEnabled(has and embeddings.embeddings_available())

    # ------------------------------------------------------------------
    def _new_folder(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            "Nouveau dossier",
            "Nom du dossier (ex: Plage, Bank/Boursorama, skyvision)",
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        # Seed avec le nom pour qu'il apparaisse dans la liste
        if embeddings.embeddings_available():
            store = exemplars.ExemplarStore.get()
            store.seed_folder_name(name)
        # Aussi : ajout dans known_folders
        sort.remember_folder(name)
        self._refresh()
        # Selection auto
        for i in range(self.folders_list.count()):
            if self.folders_list.item(i).data(Qt.ItemDataRole.UserRole) == name:
                self.folders_list.setCurrentRow(i)
                break

    def _add_examples(self) -> None:
        folder = self._selected_folder()
        if not folder:
            return
        files, _ = QFileDialog.getOpenFileNames(
            self,
            f"Ajouter des exemples pour : {folder}",
            "",
            "Fichiers supportes (*.jpg *.jpeg *.png *.bmp *.webp *.heic *.tiff *.gif *.pdf *.docx *.xlsx)",
        )
        if not files:
            return
        paths = [Path(f) for f in files if Path(f).suffix.lower() in SUPPORTED_FOR_LEARN]
        if not paths:
            QMessageBox.information(self, "Vide", "Aucun fichier supporte selectionne.")
            return
        self._start_learn(folder, paths)

    def _clear_folder_examples(self) -> None:
        folder = self._selected_folder()
        if not folder:
            return
        ans = QMessageBox.question(
            self,
            "Effacer ?",
            f"Effacer tous les exemples appris pour le dossier '{folder}' ?\n\n"
            "Le dossier reste utilisable, mais l'app perd ce qu'elle a appris dessus.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        store = exemplars.ExemplarStore.get()
        store.clear_folder(folder)
        self._refresh()

    # ------------------------------------------------------------------
    def _start_learn(self, folder: str, paths: List[Path]) -> None:
        self.add_btn.setEnabled(False)
        self.new_btn.setEnabled(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(paths))
        self.progress.setValue(0)

        self._thread = QThread(self)
        self._worker = LearnWorker(folder, paths)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_progress(self, c: int, t: int) -> None:
        self.progress.setValue(c)

    def _on_done(self, n: int) -> None:
        self.progress.setVisible(False)
        self.add_btn.setEnabled(True)
        self.new_btn.setEnabled(True)
        QMessageBox.information(
            self, "Apprentissage termine",
            f"{n} exemple(s) appris. Au prochain tri, l'app reconnaitra les fichiers similaires.",
        )
        self._refresh()

    def _on_failed(self, msg: str) -> None:
        self.progress.setVisible(False)
        self.add_btn.setEnabled(True)
        self.new_btn.setEnabled(True)
        QMessageBox.critical(self, "Erreur", msg)

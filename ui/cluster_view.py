"""Onglet Cluster : regroupe automatiquement les fichiers similaires
puis l'user nomme une fois par groupe.

Workflow :
  1. Choisir dossier source (en vrac)
  2. Choisir racine de classement (par defaut = source)
  3. Cliquer Analyser : l'app regroupe par similarite visuelle
  4. Pour chaque groupe : voir les thumbnails, taper un nom, cliquer Deplacer

Pas d'apprentissage prealable necessaire. Le nommage de chaque groupe
amorce automatiquement le store pour les prochaines analyses.
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QSize, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QLineEdit,
    QCompleter, QFileDialog, QProgressBar, QMessageBox, QScrollArea, QFrame,
    QSizePolicy, QCheckBox, QListWidget, QListWidgetItem, QDialog, QDialogButtonBox,
    QSlider,
)
from PyQt6.QtCore import QSize
from PIL import Image as _PILImage

from core import clustering, docs, exemplars, embeddings, sort
from core import api_key_store as ks, api_providers as ap
from core.clustering import Cluster
from .styles import (
    fmt_size, ACCENT, ACCENT2, TEXT, TEXT2, TEXT3, CARD, CARD2, BORDER, OK,
)
from .result_cards import make_mini_thumbnail
from .tri_mode_dialog import TriModeDialog


# ---------------------------------------------------------------------------
# Worker clustering en thread
# ---------------------------------------------------------------------------
class ApiClusterWorker(QObject):
    """Variante du ClusterWorker qui utilise une API IA cloud au lieu de CLIP local."""
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, paths: list[Path], provider: str, api_key: str) -> None:
        super().__init__()
        self.paths = paths
        self.provider = provider
        self.api_key = api_key
        import threading as _th
        self._cancel_event = _th.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            items = [ap.ApiClusterItem(path=p) for p in self.paths]
            api_clusters = ap.analyze_with_api(
                self.provider,  # type: ignore[arg-type]
                self.api_key,
                items,
                on_progress=lambda c, t, lbl: self.progress.emit(c, t, lbl),
                cancel_check=self._cancel_event.is_set,
            )
            # Convertit ApiCluster -> Cluster pour reutiliser l'UI existante
            converted: list[Cluster] = []
            for ac in api_clusters:
                converted.append(Cluster(
                    items=[it.path for it in ac.items],
                    kind="image",
                    suggested_name=ac.suggested_name,
                ))
            self.finished.emit(converted)
        except ap.ApiCancelled:
            self.failed.emit("Analyse annulee.")
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class ClusterWorker(QObject):
    progress = pyqtSignal(int, int, str)
    finished = pyqtSignal(list)  # list[Cluster]
    failed = pyqtSignal(str)

    def __init__(self, paths: list[Path], threshold: float = 0.88) -> None:
        super().__init__()
        self.paths = paths
        self.threshold = threshold

    def run(self) -> None:
        try:
            # Texte : un peu plus strict que l'image (E5 baseline elevee)
            text_threshold = min(0.97, self.threshold + 0.04)
            clusters = clustering.cluster_files(
                self.paths,
                image_threshold=self.threshold,
                text_threshold=text_threshold,
                on_progress=lambda c, t, l: self.progress.emit(c, t, l),
            )
            self.finished.emit(clusters)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(str(e))


class MoveClusterWorker(QObject):
    """Deplace un cluster vers un dossier + apprentissage simultane."""
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(int, int, list)  # (moved, learned, errors)

    def __init__(self, items: list[Path], dest_dir: Path, folder_label: str) -> None:
        super().__init__()
        self.items = items
        self.dest_dir = dest_dir
        self.folder_label = folder_label

    def run(self) -> None:
        store = exemplars.ExemplarStore.get() if embeddings.embeddings_available() else None
        moved = 0
        learned = 0
        errors: list[str] = []
        try:
            self.dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.finished.emit(0, 0, [f"mkdir : {e}"])
            return
        total = len(self.items)
        for i, src in enumerate(self.items):
            try:
                # Apprentissage AVANT le move
                if store is not None:
                    kind = docs.kind_of(src)
                    if kind == "image":
                        if store.add_image_exemplar(self.folder_label, src, defer_save=True):
                            learned += 1
                    elif kind in ("pdf", "docx", "xlsx"):
                        try:
                            text = docs.extract_text(src, max_chars=5000)
                            if text and len(text.strip()) >= 20:
                                if store.add_text_exemplar(self.folder_label, text, defer_save=True):
                                    learned += 1
                        except Exception:  # noqa: BLE001
                            pass
                # Conflit : suffixe _N
                dest = self.dest_dir / src.name
                if dest.exists():
                    n = 1
                    while True:
                        cand = self.dest_dir / f"{src.stem}_{n}{src.suffix}"
                        if not cand.exists():
                            dest = cand
                            break
                        n += 1
                src.rename(dest)
                moved += 1
                sort.remember_folder(self.folder_label)
            except OSError as e:
                errors.append(f"{src.name} : {e}")
            self.progress.emit(i + 1, total)
        if store is not None:
            store.flush()
        self.finished.emit(moved, learned, errors)


# ---------------------------------------------------------------------------
# Dialog : voir tous les fichiers d'un cluster + decocher les intrus
# ---------------------------------------------------------------------------
class ClusterContentsDialog(QDialog):
    """Liste tous les fichiers d'un cluster avec thumbnails + checkboxes.
    L'user peut decocher les fichiers qui ne devraient pas etre dans le groupe.
    Retourne la liste filtree des fichiers a deplacer."""

    def __init__(self, cluster: Cluster, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cluster = cluster
        self._checked: dict[Path, bool] = {p: True for p in cluster.items}
        self.setWindowTitle(f"Contenu du groupe ({cluster.size} fichiers)")
        self.setMinimumSize(720, 560)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            f"Decoche les fichiers qui ne devraient pas etre dans ce groupe. "
            f"Seuls les fichiers coches seront deplaces."
        )
        info.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Boutons rapides
        quick = QHBoxLayout()
        all_btn = QPushButton("Tout cocher")
        all_btn.setProperty("role", "secondary")
        all_btn.clicked.connect(self._check_all)
        quick.addWidget(all_btn)
        none_btn = QPushButton("Tout decocher")
        none_btn.setProperty("role", "secondary")
        none_btn.clicked.connect(self._uncheck_all)
        quick.addWidget(none_btn)
        quick.addStretch()
        self.count_lbl = QLabel(f"{cluster.size} / {cluster.size} coches")
        self.count_lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        quick.addWidget(self.count_lbl)
        layout.addLayout(quick)

        # Liste scrollable de fichiers
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(48, 48))
        self.list_widget.setSpacing(2)
        for p in self.cluster.items:
            item = QListWidgetItem(f"  {p.name}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(str(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            # Thumbnail comme icon
            from PyQt6.QtGui import QIcon
            from .preview import load_thumbnail
            kind = docs.kind_of(p)
            if kind == "image":
                pm = load_thumbnail(p, max_size=(96, 96))
                if pm is not None:
                    item.setIcon(QIcon(pm))
            self.list_widget.addItem(item)
        self.list_widget.itemChanged.connect(self._on_item_toggled)
        layout.addWidget(self.list_widget, stretch=1)

        # Boutons OK/Cancel
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _check_all(self) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.CheckState.Checked)

    def _uncheck_all(self) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _on_item_toggled(self, item: QListWidgetItem) -> None:
        p = item.data(Qt.ItemDataRole.UserRole)
        self._checked[p] = item.checkState() == Qt.CheckState.Checked
        n_checked = sum(1 for v in self._checked.values() if v)
        self.count_lbl.setText(f"{n_checked} / {len(self._checked)} coches")

    def kept_paths(self) -> list[Path]:
        out = []
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(it.data(Qt.ItemDataRole.UserRole))
        return out


# ---------------------------------------------------------------------------
# Widget : 1 cluster
# ---------------------------------------------------------------------------
class ClusterCard(QFrame):
    """Carte d'un groupe : nb fichiers + thumbnails + input + bouton."""

    move_requested = pyqtSignal(object, str)  # (Cluster, folder_name)

    def __init__(self, cluster: Cluster, index: int, known_folders: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cluster = cluster
        self.index = index

        self.setObjectName("ClusterCard")
        self.setStyleSheet(
            f"#ClusterCard {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: 8px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # Header
        head = QHBoxLayout()
        badge = QLabel(str(index))
        badge.setFixedSize(28, 28)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(
            f"background: {ACCENT}; color: white; border-radius: 6px; "
            f"font-weight: 800; font-size: 13px;"
        )
        head.addWidget(badge)
        info = QLabel(f"{cluster.size} fichier{'s' if cluster.size > 1 else ''}  ·  {fmt_size(cluster.total_bytes)}")
        info.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 13px;")
        head.addWidget(info)
        head.addStretch()
        # Type badge
        type_lbl = QLabel(cluster.kind.upper())
        type_lbl.setStyleSheet(
            f"background: {CARD2}; color: {TEXT2}; padding: 2px 8px; "
            f"border-radius: 3px; font-size: 9px; font-weight: 700;"
        )
        head.addWidget(type_lbl)
        outer.addLayout(head)

        # Strip de thumbnails (max 6 visibles, +N pour le reste = cliquable)
        thumbs = QHBoxLayout()
        thumbs.setSpacing(6)
        max_show = 6
        for p in cluster.items[:max_show]:
            thumbs.addWidget(make_mini_thumbnail(p, size=72))
        if cluster.size > max_show:
            rest = QPushButton(f"+{cluster.size - max_show}\nvoir tout")
            rest.setFixedSize(72, 72)
            rest.setStyleSheet(
                f"background: {CARD2}; color: {TEXT}; border: 1px solid {ACCENT}; "
                f"border-radius: 4px; font-size: 11px; font-weight: 700;"
            )
            rest.setToolTip("Voir tous les fichiers du groupe et decocher les intrus")
            rest.clicked.connect(self._open_contents_dialog)
            thumbs.addWidget(rest)
        # Bouton "Voir tout" meme pour les petits clusters (si plus de 1 fichier)
        elif cluster.size > 1:
            see_btn = QPushButton("Voir\ntout")
            see_btn.setFixedSize(72, 72)
            see_btn.setStyleSheet(
                f"background: {CARD2}; color: {TEXT2}; border: 1px solid {BORDER}; "
                f"border-radius: 4px; font-size: 11px;"
            )
            see_btn.setToolTip("Voir tous les fichiers du groupe et decocher les intrus")
            see_btn.clicked.connect(self._open_contents_dialog)
            thumbs.addWidget(see_btn)
        thumbs.addStretch()
        outer.addLayout(thumbs)

        # Liste de noms de fichiers (1ere ligne preview)
        first_names = ", ".join(p.name for p in cluster.items[:3])
        if cluster.size > 3:
            first_names += f", ... (+{cluster.size - 3})"
        preview = QLabel(first_names)
        preview.setStyleSheet(f"color: {TEXT3}; font-size: 10px;")
        preview.setWordWrap(False)
        preview.setMaximumHeight(16)
        outer.addWidget(preview)

        # Input + bouton
        action = QHBoxLayout()
        action.addWidget(QLabel("Nom du dossier :"))
        self.folder_input = QLineEdit()
        # Si l'API a propose un nom, pre-remplir (l'user peut modifier)
        if cluster.suggested_name:
            self.folder_input.setText(cluster.suggested_name)
        self.folder_input.setPlaceholderText("Tape un nom (ex: skyvision, Plage, Factures...)")
        self.folder_input.setStyleSheet(
            f"background: {CARD2}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 6px 10px;"
        )
        # Autocomplete sur dossiers deja utilises
        completer = QCompleter(known_folders, self.folder_input)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.folder_input.setCompleter(completer)
        self.folder_input.returnPressed.connect(self._on_move_clicked)
        action.addWidget(self.folder_input, stretch=1)

        self.move_btn = QPushButton("Deplacer ce groupe")
        self.move_btn.clicked.connect(self._on_move_clicked)
        action.addWidget(self.move_btn)

        self.skip_btn = QPushButton("Ignorer")
        self.skip_btn.setProperty("role", "secondary")
        self.skip_btn.clicked.connect(self._on_skip_clicked)
        action.addWidget(self.skip_btn)

        outer.addLayout(action)

    def _open_contents_dialog(self) -> None:
        """Ouvre la liste complete du cluster pour voir/decocher."""
        dlg = ClusterContentsDialog(self.cluster, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            kept = dlg.kept_paths()
            if not kept:
                QMessageBox.information(self, "Vide", "Aucun fichier coche, le groupe est vide.")
                return
            # Modifie le cluster sur place pour ne garder que les fichiers coches
            self.cluster.items = kept
            # Force le re-render visuel (mise a jour du compteur)
            QMessageBox.information(
                self, "Mise a jour",
                f"Groupe filtre : {len(kept)} fichier(s) conserve(s). Re-lance Analyser ou clique Deplacer pour appliquer."
            )

    def _on_move_clicked(self) -> None:
        name = self.folder_input.text().strip()
        if not name:
            QMessageBox.information(self, "Nom requis", "Tape un nom de dossier avant de deplacer.")
            return
        self.move_requested.emit(self.cluster, name)

    def _on_skip_clicked(self) -> None:
        # Emet move avec un nom magique -> la vue retire la carte sans rien faire
        self.move_requested.emit(self.cluster, "__SKIP__")

    def set_busy(self, busy: bool) -> None:
        self.move_btn.setEnabled(not busy)
        self.skip_btn.setEnabled(not busy)
        self.folder_input.setEnabled(not busy)


# ---------------------------------------------------------------------------
# Vue principale
# ---------------------------------------------------------------------------
SUPPORTED_EXTS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".tiff", ".tif", ".gif",
    ".pdf", ".docx", ".xlsx",
}

# Filtres : ignore les fichiers qui sont quasi-surement pas des contenus user
MIN_FILE_SIZE_BYTES = 30 * 1024   # 30 KB minimum
MIN_IMAGE_DIM_PX = 200            # images < 200x200 = icones
# Patterns de chemins a exclure (case-insensitive)
EXCLUDE_PATH_PATTERNS = [
    ".git", "node_modules", "__pycache__", "venv", ".venv",
    "appdata\\local\\temp", "appdata\\roaming",
    "program files", "windows", "system32",
    "$recycle.bin", ".cache", "thumbnails", "thumb",
]


def _is_relevant_file(path: Path) -> bool:
    """Filtre les fichiers qui sont vraisemblablement des contenus user."""
    # Taille
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size < MIN_FILE_SIZE_BYTES:
        return False
    # Chemin (exclure les dossiers techniques)
    path_str = str(path).lower()
    for pat in EXCLUDE_PATH_PATTERNS:
        if pat in path_str:
            return False
    # Pour les images, verifie les dimensions
    ext = path.suffix.lower()
    if ext in {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".tiff", ".tif", ".gif"}:
        try:
            with _PILImage.open(path) as img:
                w, h = img.size
            if w < MIN_IMAGE_DIM_PX or h < MIN_IMAGE_DIM_PX:
                return False
        except Exception:  # noqa: BLE001
            return False
    return True


class ClusterView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cards: list[ClusterCard] = []
        self.sources: list[Path] = []  # fichiers ET dossiers (l'user ajoute ce qu'il veut)
        self._dest_root: Optional[Path] = None
        self._worker: ClusterWorker | None = None
        self._thread: QThread | None = None
        self._move_worker: MoveClusterWorker | None = None
        self._move_thread: QThread | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("Tri par ressemblance")
        title.setStyleSheet(f"color: {TEXT}; font-size: 22px; font-weight: 800;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Regroupe automatiquement les fichiers qui se ressemblent. "
            "Pour chaque groupe, tape un nom de dossier et clique Deplacer. "
            "Pas d'apprentissage prealable necessaire."
        )
        subtitle.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Liste des sources : fichiers ou dossiers ajoutes par l'user
        src_lbl = QLabel("Fichiers et dossiers a trier :")
        src_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600;")
        layout.addWidget(src_lbl)
        src_box = QHBoxLayout()
        self.sources_list = QListWidget()
        self.sources_list.setMaximumHeight(120)
        src_box.addWidget(self.sources_list, stretch=1)
        src_btns = QVBoxLayout()
        add_files_btn = QPushButton("+ Ajouter fichiers...")
        add_files_btn.clicked.connect(self._add_files)
        src_btns.addWidget(add_files_btn)
        add_dir_btn = QPushButton("+ Ajouter dossier...")
        add_dir_btn.clicked.connect(self._add_dir)
        src_btns.addWidget(add_dir_btn)
        rm_btn = QPushButton("Retirer")
        rm_btn.setProperty("role", "secondary")
        rm_btn.clicked.connect(self._remove_source)
        src_btns.addWidget(rm_btn)
        clear_btn = QPushButton("Vider")
        clear_btn.setProperty("role", "secondary")
        clear_btn.clicked.connect(self._clear_sources)
        src_btns.addWidget(clear_btn)
        src_btns.addStretch()
        src_box.addLayout(src_btns)
        layout.addLayout(src_box)

        # Racine de classement
        dest_row = QHBoxLayout()
        dest_lbl = QLabel("Racine de classement :")
        dest_lbl.setFixedWidth(160)
        dest_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600;")
        dest_row.addWidget(dest_lbl)
        self.dest_input = QLineEdit()
        self.dest_input.setReadOnly(True)
        self.dest_input.setPlaceholderText("(par defaut = meme dossier que source)")
        self.dest_input.setStyleSheet(
            f"background: {CARD}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 6px 10px;"
        )
        dest_row.addWidget(self.dest_input, stretch=1)
        choose_dest = QPushButton("Changer...")
        choose_dest.setProperty("role", "secondary")
        choose_dest.clicked.connect(self._choose_dest)
        dest_row.addWidget(choose_dest)
        layout.addLayout(dest_row)

        # Options
        opt_row = QHBoxLayout()
        self.recursive_cb = QCheckBox("Inclure sous-dossiers")
        self.recursive_cb.setChecked(False)
        opt_row.addWidget(self.recursive_cb)
        self.filters_cb = QCheckBox("Ignorer icones et fichiers systeme")
        self.filters_cb.setChecked(False)
        opt_row.addWidget(self.filters_cb)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # Seuil de similarite (slider)
        sim_row = QHBoxLayout()
        sim_lbl = QLabel("Stricte du regroupement :")
        sim_lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        sim_row.addWidget(sim_lbl)
        self.sim_slider = QSlider(Qt.Orientation.Horizontal)
        self.sim_slider.setMinimum(70)   # 0.70 = tres permissif (gros groupes)
        self.sim_slider.setMaximum(95)   # 0.95 = tres strict (petits groupes precis)
        self.sim_slider.setValue(88)     # defaut : 0.88 = strict (avant c'etait 0.82)
        self.sim_slider.setFixedWidth(220)
        self.sim_slider.valueChanged.connect(self._update_sim_label)
        sim_row.addWidget(self.sim_slider)
        self.sim_value_lbl = QLabel("0.88 (strict)")
        self.sim_value_lbl.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        self.sim_value_lbl.setFixedWidth(110)
        sim_row.addWidget(self.sim_value_lbl)
        sim_row.addStretch()
        layout.addLayout(sim_row)

        # Actions
        actions = QHBoxLayout()
        actions.addStretch()
        self.analyze_btn = QPushButton("Analyser et regrouper")
        self.analyze_btn.clicked.connect(self._start_clustering)
        actions.addWidget(self.analyze_btn)
        layout.addLayout(actions)

        # Progress
        self.progress_label = QLabel("")
        self.progress_label.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        layout.addWidget(self.progress_label)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        # Container scrollable des clusters
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._container = QWidget()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(10)
        self._empty_lbl = QLabel(
            "Choisis un dossier en vrac et clique \"Analyser et regrouper\"."
        )
        self._empty_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 12px;")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._container_layout.addWidget(self._empty_lbl)
        self._container_layout.addStretch()
        self.scroll.setWidget(self._container)
        layout.addWidget(self.scroll, stretch=1)

        # Footer
        self.footer = QLabel("0 groupe")
        self.footer.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        layout.addWidget(self.footer)

    # ==================================================================
    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self, "Ajouter des fichiers a trier",
            "", "Fichiers supportes (*.jpg *.jpeg *.png *.bmp *.webp *.heic *.tiff *.gif *.pdf *.docx *.xlsx);;Tous les fichiers (*)"
        )
        if not files:
            return
        for f in files:
            p = Path(f)
            if p not in self.sources:
                self.sources.append(p)
                QListWidgetItem(f"[fichier] {p.name}    -    {p.parent}", self.sources_list)

    def _add_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Ajouter un dossier a trier")
        if not folder:
            return
        p = Path(folder)
        if p not in self.sources:
            self.sources.append(p)
            QListWidgetItem(f"[dossier] {p}", self.sources_list)

    def _remove_source(self) -> None:
        for it in self.sources_list.selectedItems():
            row = self.sources_list.row(it)
            self.sources_list.takeItem(row)
            del self.sources[row]

    def _clear_sources(self) -> None:
        self.sources.clear()
        self.sources_list.clear()

    def _update_sim_label(self, val: int) -> None:
        v = val / 100.0
        if v >= 0.92:
            label = f"{v:.2f} (tres strict)"
        elif v >= 0.85:
            label = f"{v:.2f} (strict)"
        elif v >= 0.78:
            label = f"{v:.2f} (moyen)"
        else:
            label = f"{v:.2f} (permissif)"
        self.sim_value_lbl.setText(label)

    def _choose_dest(self) -> None:
        f = QFileDialog.getExistingDirectory(self, "Racine de classement")
        if f:
            self._dest_root = Path(f)
            self.dest_input.setText(f)

    # ==================================================================
    def _start_clustering(self) -> None:
        if not self.sources:
            QMessageBox.information(
                self, "Vide",
                "Ajoute des fichiers ou des dossiers a trier (boutons + Ajouter...)."
            )
            return
        # Collecte tous les fichiers candidats depuis les sources
        candidates: list[Path] = []
        for s in self.sources:
            if s.is_file():
                candidates.append(s)
            elif s.is_dir():
                if self.recursive_cb.isChecked():
                    candidates.extend(p for p in s.rglob("*") if p.is_file())
                else:
                    candidates.extend(p for p in s.iterdir() if p.is_file())
        # Filtre par extension supportee
        candidates = [p for p in candidates if p.suffix.lower() in SUPPORTED_EXTS]
        # Deduplication (au cas ou)
        seen = set()
        unique = []
        for p in candidates:
            rp = p.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            unique.append(p)
        candidates = unique
        n_before = len(candidates)
        # Filtres optionnels
        if self.filters_cb.isChecked():
            files = [p for p in candidates if _is_relevant_file(p)]
        else:
            files = candidates
        n_filtered = n_before - len(files)
        if not files:
            QMessageBox.information(
                self, "Vide",
                f"Aucun fichier a analyser ({n_before} candidats, {n_filtered} ecartes)."
            )
            return
        msg = f"{len(files)} fichier(s) a analyser"
        if n_filtered > 0:
            msg += f" ({n_filtered} ecarte(s) par filtre)"
        self.progress_label.setText(msg + "...")

        # === Choix du mode : local CLIP vs API cloud ===
        mode_dlg = TriModeDialog(self)
        if mode_dlg.exec() != QDialog.DialogCode.Accepted or not mode_dlg.chosen_mode:
            self.progress_label.setText("")
            return
        mode = mode_dlg.chosen_mode

        if mode == "local" and not embeddings.embeddings_available():
            QMessageBox.critical(
                self, "Modeles indispo",
                "Le clustering local necessite les modeles ONNX (CLIP). Verifie le bundle."
            )
            return

        self._clear_cards()
        self._empty_lbl.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(files))
        self.progress_label.setText("Analyse...")
        self.analyze_btn.setEnabled(False)

        self._thread = QThread(self)
        if mode == "local":
            threshold = self.sim_slider.value() / 100.0
            self._worker = ClusterWorker(files, threshold=threshold)
        else:
            # Mode API : utilise le provider configure
            provider = ks.get_configured_provider()
            api_key = ks.load_api_key(provider) if provider else None
            if not provider or not api_key:
                QMessageBox.critical(self, "Config manquante", "Cle API introuvable.")
                self.analyze_btn.setEnabled(True)
                self.progress.setVisible(False)
                return
            self._worker = ApiClusterWorker(files, provider, api_key)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_clustering_done)
        self._worker.failed.connect(self._on_clustering_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    def _on_progress(self, c: int, t: int, label: str) -> None:
        if self.progress.maximum() != t:
            self.progress.setRange(0, max(1, t))
        self.progress.setValue(min(c, t))
        self.progress_label.setText(label)

    def _on_clustering_done(self, clusters: list) -> None:
        self.progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        if not clusters:
            self._empty_lbl.setVisible(True)
            self._empty_lbl.setText("Aucun groupe forme.")
            self.footer.setText("0 groupe")
            return
        known = [f for f, _ in sort.load_known_folders()]
        # Inclus aussi les dossiers ayant des exemplars (sans usage encore)
        if embeddings.embeddings_available():
            store = exemplars.ExemplarStore.get()
            known = sorted(set(known) | set(store.known_folders()))

        for i, c in enumerate(clusters, start=1):
            if c.size < 1:
                continue
            card = ClusterCard(c, index=i, known_folders=known)
            card.move_requested.connect(self._on_move_requested)
            self.cards.append(card)
            self._container_layout.insertWidget(self._container_layout.count() - 1, card)
        self.footer.setText(f"{len(self.cards)} groupe(s) formes a partir des fichiers analyses.")
        self.progress_label.setText(f"Termine : {len(self.cards)} groupes.")

    def _on_clustering_failed(self, msg: str) -> None:
        self.progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        QMessageBox.critical(self, "Erreur clustering", msg)

    # ==================================================================
    def _on_move_requested(self, cluster: Cluster, folder_name: str) -> None:
        # Skip = retire la carte sans rien faire
        if folder_name == "__SKIP__":
            self._remove_card_for_cluster(cluster)
            self._update_footer()
            return
        # Determine root : explicite ou 1er dossier des sources
        if self._dest_root is not None:
            root = self._dest_root
        else:
            # Cherche le premier dossier dans les sources, sinon parent du 1er fichier
            root = None
            for s in self.sources:
                if s.is_dir():
                    root = s
                    break
            if root is None and self.sources:
                root = self.sources[0].parent
            if root is None:
                QMessageBox.warning(self, "Pas de racine",
                                    "Choisis une racine de classement (bouton Changer...).")
                return
        dest_dir = root.joinpath(*folder_name.replace("\\", "/").split("/"))

        # Trouve la card du cluster + lock
        card = self._find_card(cluster)
        if card is not None:
            card.set_busy(True)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(cluster.items))
        self.progress_label.setText(f"Deplacement de {cluster.size} fichiers vers {folder_name}...")

        self._move_thread = QThread(self)
        self._move_worker = MoveClusterWorker(list(cluster.items), dest_dir, folder_name)
        self._move_worker.moveToThread(self._move_thread)
        self._move_thread.started.connect(self._move_worker.run)
        self._move_worker.progress.connect(lambda c, t: self.progress.setValue(c))
        self._move_worker.finished.connect(
            lambda moved, learned, errs: self._on_cluster_moved(cluster, moved, learned, errs)
        )
        self._move_worker.finished.connect(self._move_thread.quit)
        self._move_thread.finished.connect(self._cleanup_move_thread)
        self._move_thread.start()

    def _on_cluster_moved(self, cluster: Cluster, moved: int, learned: int, errors: list) -> None:
        self.progress.setVisible(False)
        if errors:
            QMessageBox.warning(
                self, "Deplacement avec erreurs",
                f"Deplace : {moved}\nApprentissage : {learned}\n\nErreurs :\n" + "\n".join(errors[:10]),
            )
        else:
            self.progress_label.setText(
                f"Deplace : {moved} fichiers, l'app a appris {learned} exemple(s)."
            )
        # Retire la carte du cluster traite
        self._remove_card_for_cluster(cluster)
        self._update_footer()

    def _cleanup_move_thread(self) -> None:
        if self._move_worker is not None:
            self._move_worker.deleteLater()
            self._move_worker = None
        if self._move_thread is not None:
            self._move_thread.deleteLater()
            self._move_thread = None

    def _find_card(self, cluster: Cluster) -> Optional[ClusterCard]:
        for c in self.cards:
            if c.cluster is cluster:
                return c
        return None

    def _remove_card_for_cluster(self, cluster: Cluster) -> None:
        card = self._find_card(cluster)
        if card is None:
            return
        self._container_layout.removeWidget(card)
        self.cards.remove(card)
        card.deleteLater()

    def _clear_cards(self) -> None:
        for c in self.cards:
            self._container_layout.removeWidget(c)
            c.deleteLater()
        self.cards = []

    def _update_footer(self) -> None:
        if not self.cards:
            self.footer.setText("Tous les groupes traites.")
            self._empty_lbl.setVisible(True)
            self._empty_lbl.setText("Tous les groupes ont ete traites.")
        else:
            self.footer.setText(f"{len(self.cards)} groupe(s) restant(s).")

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
from PyQt6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
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
from core.i18n import t
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

    def __init__(self, paths: list[Path], threshold: float = 0.78) -> None:
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
        self.setWindowTitle(t("dlg.cluster.title", n=cluster.size))
        self.setMinimumSize(720, 560)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(t("dlg.cluster.info"))
        info.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        info.setWordWrap(True)
        layout.addWidget(info)

        # Boutons rapides
        quick = QHBoxLayout()
        all_btn = QPushButton(t("dlg.dup.check_all"))
        all_btn.setProperty("role", "secondary")
        all_btn.clicked.connect(self._check_all)
        quick.addWidget(all_btn)
        none_btn = QPushButton(t("dlg.dup.uncheck_all"))
        none_btn.setProperty("role", "secondary")
        none_btn.clicked.connect(self._uncheck_all)
        quick.addWidget(none_btn)
        quick.addStretch()
        self.count_lbl = QLabel(t("dlg.cluster.checked", n=self.cluster.size, total=self.cluster.size))
        self.count_lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        quick.addWidget(self.count_lbl)
        layout.addLayout(quick)

        # Liste scrollable de fichiers : on construit d'abord SANS thumbnails
        # (instantane), puis on les charge en deferred via QTimer pour eviter
        # de bloquer/crasher si un fichier pose probleme. Le dialog s'ouvre
        # immediatement et les vignettes apparaissent une par une.
        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(48, 48))
        self.list_widget.setSpacing(2)
        self._items_to_load: list[tuple[int, Path]] = []
        for i, p in enumerate(self.cluster.items):
            item = QListWidgetItem(f"  {p.name}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setToolTip(str(p))
            item.setData(Qt.ItemDataRole.UserRole, p)
            self.list_widget.addItem(item)
            kind = docs.kind_of(p)
            if kind == "image":
                self._items_to_load.append((i, p))
        self.list_widget.itemChanged.connect(self._on_item_toggled)
        layout.addWidget(self.list_widget, stretch=1)

        # Boutons OK/Cancel
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

        # Demarre le chargement deferred des thumbnails apres l'ouverture du
        # dialog. QTimer.singleShot(0) = a la prochaine boucle d'event, donc
        # le dialog est deja visible et reactif.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(0, self._load_next_thumbnail)

    def _load_next_thumbnail(self) -> None:
        """Charge la prochaine thumbnail de la queue. Auto-rappele jusqu'a
        epuisement de la queue. Chaque load est wrappe en try/except : si
        un fichier crashe, on saute juste celui-la, le dialog continue.
        """
        if not self._items_to_load:
            return
        idx, path = self._items_to_load.pop(0)
        try:
            from PyQt6.QtGui import QIcon
            from .preview import load_thumbnail
            pm = load_thumbnail(path, max_size=(96, 96))
            if pm is not None:
                item = self.list_widget.item(idx)
                if item is not None:
                    item.setIcon(QIcon(pm))
        except Exception:  # noqa: BLE001
            pass  # fichier corrompu, on ignore et on continue avec le suivant
        # Programme le suivant (cede le controle a l'event loop entre chaque)
        if self._items_to_load:
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self._load_next_thumbnail)

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
        self.count_lbl.setText(t("dlg.cluster.checked", n=n_checked, total=len(self._checked)))

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
    recluster_loose_requested = pyqtSignal()  # bouton "Elargir" : re-cluster global

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
        self._count_label = QLabel(f"{cluster.size} fichier{'s' if cluster.size > 1 else ''}  ·  {fmt_size(cluster.total_bytes)}")
        self._count_label.setStyleSheet(f"color: {TEXT}; font-weight: 600; font-size: 13px;")
        head.addWidget(self._count_label)
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

        # Boutons secondaires discrets : "Voir / decocher" + "Elargir"
        self._see_btn = None
        if cluster.size > 1:
            sec_row = QHBoxLayout()
            sec_row.setSpacing(6)
            self._see_btn = QPushButton(t("card.see_files", n=cluster.size))
            self._see_btn.setProperty("role", "secondary")
            self._see_btn.setStyleSheet(
                f"color: {TEXT2}; background: transparent; border: 1px solid {BORDER}; "
                f"border-radius: 4px; padding: 4px 10px; font-size: 11px;"
            )
            self._see_btn.setToolTip(t("card.see_files_tip"))
            self._see_btn.clicked.connect(self._open_contents_dialog)
            sec_row.addWidget(self._see_btn)
            # Bouton "Elargir" : relance le clustering global avec un seuil -0.05.
            elargir = QPushButton(t("card.elargir"))
            elargir.setProperty("role", "secondary")
            elargir.setStyleSheet(
                f"color: {ACCENT2}; background: transparent; border: 1px solid {ACCENT}; "
                f"border-radius: 4px; padding: 4px 10px; font-size: 11px;"
            )
            elargir.setToolTip(t("card.elargir_tip"))
            elargir.clicked.connect(self.recluster_loose_requested.emit)
            sec_row.addWidget(elargir)
            sec_row.addStretch()
            outer.addLayout(sec_row)

        # Input + bouton (Deplacer est le bouton PRIMAIRE, bien visible)
        action = QHBoxLayout()
        action.addWidget(QLabel(t("card.folder_label")))
        self.folder_input = QLineEdit()
        # Si l'API a propose un nom, pre-remplir (l'user peut modifier)
        if cluster.suggested_name:
            self.folder_input.setText(cluster.suggested_name)
        self.folder_input.setPlaceholderText(t("card.folder_placeholder"))
        self.folder_input.setStyleSheet(
            f"background: {CARD2}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 6px 10px;"
        )
        # Autocomplete sur dossiers deja utilises
        self._completer = QCompleter(known_folders, self.folder_input)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.folder_input.setCompleter(self._completer)
        self.folder_input.returnPressed.connect(self._on_move_clicked)
        action.addWidget(self.folder_input, stretch=1)

        # Bouton primaire bien visible : c'est l'action principale d'un cluster
        self.move_btn = QPushButton(t("card.move_btn"))
        self.move_btn.setStyleSheet(
            f"background: {ACCENT}; color: white; padding: 8px 14px; "
            f"border-radius: 5px; font-weight: 700; font-size: 12px;"
        )
        self.move_btn.setToolTip(t("card.move_btn_tip"))
        self.move_btn.clicked.connect(self._on_move_clicked)
        action.addWidget(self.move_btn)

        self.skip_btn = QPushButton(t("card.skip"))
        self.skip_btn.setProperty("role", "secondary")
        self.skip_btn.setStyleSheet(
            f"color: {TEXT2}; background: transparent; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 6px 10px;"
        )
        self.skip_btn.clicked.connect(self._on_skip_clicked)
        action.addWidget(self.skip_btn)

        outer.addLayout(action)

    def _open_contents_dialog(self) -> None:
        """Ouvre la liste complete du cluster pour voir/decocher.

        Pas de popup confus apres validation : on met juste a jour le compteur
        de fichiers de la card silencieusement. L'user voit le nouveau total
        et peut directement cliquer Deplacer.
        """
        dlg = ClusterContentsDialog(self.cluster, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            kept = dlg.kept_paths()
            if not kept:
                QMessageBox.information(self, t("common.empty"), t("card.name_required"))
                return
            # Modifie le cluster sur place pour ne garder que les fichiers coches
            self.cluster.items = kept
            # Met a jour le compteur affiche sur la card
            if hasattr(self, "_count_label") and self._count_label is not None:
                size_total = fmt_size(sum(p.stat().st_size for p in kept if p.exists()))
                self._count_label.setText(f"{len(kept)} · {size_total}")
            # Met a jour le texte du bouton "Voir / decocher" aussi
            if hasattr(self, "_see_btn") and self._see_btn is not None:
                self._see_btn.setText(t("card.see_files", n=len(kept)))

    def _on_move_clicked(self) -> None:
        name = self.folder_input.text().strip()
        if not name:
            QMessageBox.information(self, t("common.warning"), t("card.name_required"))
            return
        self.move_requested.emit(self.cluster, name)

    def _on_skip_clicked(self) -> None:
        # Emet move avec un nom magique -> la vue retire la carte sans rien faire
        self.move_requested.emit(self.cluster, "__SKIP__")

    def set_busy(self, busy: bool) -> None:
        self.move_btn.setEnabled(not busy)
        self.skip_btn.setEnabled(not busy)
        self.folder_input.setEnabled(not busy)

    def update_known_folders(self, folders: list[str]) -> None:
        """Mets a jour la liste des dossiers proposes en autocomplete.

        Appele apres qu'un autre cluster ait ete deplace, pour que son nom
        de dossier devienne immediatement disponible en suggestion ici.
        """
        from PyQt6.QtCore import QStringListModel
        if hasattr(self, "_completer") and self._completer is not None:
            model = self._completer.model()
            if isinstance(model, QStringListModel):
                model.setStringList(folders)
            else:
                self._completer.setModel(QStringListModel(folders, self._completer))


# ---------------------------------------------------------------------------
# Vue principale
# ---------------------------------------------------------------------------
SUPPORTED_EXTS = {
    # Images : CLIP genere des embeddings visuels
    ".jpg", ".jpeg", ".png", ".bmp", ".webp", ".heic", ".tiff", ".tif", ".gif",
    # Documents : E5 genere des embeddings textuels (texte extrait)
    ".pdf", ".docx", ".xlsx",
    # Videos : pas d'embedding possible, finiront en singletons 'other' mais
    # apparaitront dans la liste de groupes (l'user peut les deplacer manuellement)
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".3gp", ".wmv", ".flv",
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
        self._pending_clusters: list = []
        self._rendered_count: int = 0
        self._known_folders_cache: list[str] = []
        self._more_btn_clusters = None
        self._worker: ClusterWorker | None = None
        self._thread: QThread | None = None
        self._move_worker: MoveClusterWorker | None = None
        self._move_thread: QThread | None = None
        # Paths utilises pour le dernier clustering, pour pouvoir relancer
        # un re-clustering plus permissif sans re-scanner les sources.
        self._last_clustered_paths: list[Path] = []
        self._last_used_threshold: float = 0.78
        self._build_ui()
        # Drag-and-drop natif depuis l'Explorateur Windows : plus fiable que
        # le file picker (qui peut tronquer silencieusement les selections
        # multiples). L'user glisse ses fichiers/dossiers et tout passe.
        self.setAcceptDrops(True)

    # ==================================================================
    # Drag-and-drop natif (l'user glisse depuis l'Explorateur)
    # ==================================================================
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        # Accepte tout drag qui contient des URLs de fichiers locaux
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        """Ajoute a self.sources tous les fichiers/dossiers droppes."""
        urls = event.mimeData().urls()
        if not urls:
            return
        n_added_files = 0
        n_added_dirs = 0
        n_already = 0
        for url in urls:
            if not url.isLocalFile():
                continue
            try:
                p = Path(url.toLocalFile())
            except Exception:  # noqa: BLE001
                continue
            if p in self.sources:
                n_already += 1
                continue
            self.sources.append(p)
            if p.is_file():
                QListWidgetItem(f"[fichier] {p.name}    -    {p.parent}", self.sources_list)
                n_added_files += 1
            elif p.is_dir():
                QListWidgetItem(f"[dossier] {p}", self.sources_list)
                n_added_dirs += 1
        event.acceptProposedAction()
        # Feedback discret dans le footer (pas de popup intrusive)
        if n_added_files or n_added_dirs:
            parts = []
            if n_added_files:
                parts.append(f"{n_added_files} fichier(s)")
            if n_added_dirs:
                parts.append(f"{n_added_dirs} dossier(s)")
            if n_already:
                parts.append(f"{n_already} deja present(s)")
            self.progress_label.setText("Ajoute : " + " + ".join(parts))

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Ligne titre + bouton Retour (visible uniquement quand resultats affiches)
        title_row = QHBoxLayout()
        self.back_btn = QPushButton(t("common.back"))
        self.back_btn.setProperty("role", "secondary")
        self.back_btn.setToolTip(t("sort.back_tip"))
        self.back_btn.clicked.connect(self._back_to_setup)
        self.back_btn.setVisible(False)
        title_row.addWidget(self.back_btn)
        title = QLabel(t("sort.title"))
        title.setStyleSheet(f"color: {TEXT}; font-size: 22px; font-weight: 800;")
        title_row.addWidget(title)
        title_row.addStretch()
        layout.addLayout(title_row)

        subtitle = QLabel(t("sort.subtitle"))
        subtitle.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Liste des sources : fichiers ou dossiers ajoutes par l'user
        src_lbl = QLabel(t("sort.sources_label"))
        src_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600;")
        layout.addWidget(src_lbl)
        src_box = QHBoxLayout()
        self.sources_list = QListWidget()
        self.sources_list.setMaximumHeight(120)
        src_box.addWidget(self.sources_list, stretch=1)
        src_btns = QVBoxLayout()
        add_files_btn = QPushButton(t("sort.add_files"))
        add_files_btn.clicked.connect(self._add_files)
        src_btns.addWidget(add_files_btn)
        add_dir_btn = QPushButton(t("sort.add_dir"))
        add_dir_btn.clicked.connect(self._add_dir)
        src_btns.addWidget(add_dir_btn)
        rm_btn = QPushButton(t("sort.remove"))
        rm_btn.setProperty("role", "secondary")
        rm_btn.clicked.connect(self._remove_source)
        src_btns.addWidget(rm_btn)
        clear_btn = QPushButton(t("sort.clear"))
        clear_btn.setProperty("role", "secondary")
        clear_btn.setToolTip(t("sort.clear_tip"))
        clear_btn.clicked.connect(self._clear_sources)
        src_btns.addWidget(clear_btn)
        src_btns.addStretch()
        src_box.addLayout(src_btns)
        layout.addLayout(src_box)

        # Racine de classement
        dest_row = QHBoxLayout()
        dest_lbl = QLabel(t("sort.dest_root"))
        dest_lbl.setFixedWidth(160)
        dest_lbl.setStyleSheet(f"color: {TEXT}; font-weight: 600;")
        dest_row.addWidget(dest_lbl)
        self.dest_input = QLineEdit()
        self.dest_input.setReadOnly(True)
        self.dest_input.setPlaceholderText(t("sort.dest_placeholder"))
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
        self.recursive_cb = QCheckBox(t("sort.recursive"))
        self.recursive_cb.setChecked(False)
        opt_row.addWidget(self.recursive_cb)
        self.filters_cb = QCheckBox(t("sort.filters"))
        self.filters_cb.setChecked(False)
        opt_row.addWidget(self.filters_cb)
        opt_row.addStretch()
        layout.addLayout(opt_row)

        # Seuil de similarite (slider)
        sim_row = QHBoxLayout()
        sim_lbl = QLabel(t("sort.threshold"))
        sim_lbl.setStyleSheet(f"color: {TEXT}; font-size: 11px;")
        sim_row.addWidget(sim_lbl)
        self.sim_slider = QSlider(Qt.Orientation.Horizontal)
        self.sim_slider.setMinimum(70)   # 0.70 = tres permissif (gros groupes)
        self.sim_slider.setMaximum(95)   # 0.95 = tres strict (petits groupes precis)
        # Defaut : 0.78. Test sur photos similaires (KakaoTalk multi-envois) montre
        # qu'a 0.88 on rate 70% des paires reellement similaires (la mediane de
        # similarite est ~0.85). 0.78 capture 70% des vraies similarites avec
        # ZERO faux-positif sur le cross-set teste.
        self.sim_slider.setValue(78)
        self.sim_slider.setFixedWidth(220)
        self.sim_slider.valueChanged.connect(self._update_sim_label)
        sim_row.addWidget(self.sim_slider)
        self.sim_value_lbl = QLabel("0.78 (moyen)")
        self.sim_value_lbl.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        self.sim_value_lbl.setFixedWidth(110)
        sim_row.addWidget(self.sim_value_lbl)
        sim_row.addStretch()
        layout.addLayout(sim_row)

        # Petit help text discret sous le slider (l'user n'a pas besoin de
        # comprendre 'cosinus', juste l'effet pratique du curseur)
        sim_help = QLabel(t("sort.threshold_help"))
        sim_help.setStyleSheet(f"color: {TEXT3}; font-size: 10px; font-style: italic;")
        sim_help.setWordWrap(True)
        layout.addWidget(sim_help)

        # Actions
        actions = QHBoxLayout()
        actions.addStretch()
        self.analyze_btn = QPushButton(t("sort.analyze"))
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
        self._empty_lbl = QLabel(t("sort.empty"))
        self._empty_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 12px;")
        self._empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._container_layout.addWidget(self._empty_lbl)
        self._container_layout.addStretch()
        self.scroll.setWidget(self._container)
        layout.addWidget(self.scroll, stretch=1)

        # Bottom bar : actions globales
        bottom = QHBoxLayout()
        bottom.addStretch()

        # Bouton "Deplacer les isoles vers un album commun"
        # Apparait si au moins 1 cluster de taille 1 (singleton) existe.
        self.move_singletons_btn = QPushButton(t("sort.move_singletons", n=0))
        self.move_singletons_btn.setStyleSheet(
            f"background: {CARD2}; color: {TEXT}; padding: 8px 14px; "
            f"border-radius: 5px; font-weight: 600; font-size: 11px; "
            f"border: 1px solid {ACCENT2};"
        )
        self.move_singletons_btn.setToolTip(t("sort.move_singletons_tip"))
        self.move_singletons_btn.clicked.connect(self._move_all_singletons)
        self.move_singletons_btn.setVisible(False)
        bottom.addWidget(self.move_singletons_btn)

        self.move_all_btn = QPushButton(t("sort.move_all"))
        self.move_all_btn.setStyleSheet(
            f"background: {OK}; color: black; padding: 8px 18px; "
            f"border-radius: 5px; font-weight: 800; font-size: 12px;"
        )
        self.move_all_btn.setToolTip(t("sort.move_all_tip"))
        self.move_all_btn.clicked.connect(self._start_move_all)
        self.move_all_btn.setVisible(False)  # n'apparait que quand y a des clusters
        bottom.addWidget(self.move_all_btn)
        layout.addLayout(bottom)

        # Footer
        self.footer = QLabel(t("sort.footer_zero"))
        self.footer.setStyleSheet(f"color: {TEXT2}; font-size: 11px;")
        layout.addWidget(self.footer)

        # Etat interne pour la queue "Deplacer tout"
        self._move_all_queue: list = []
        self._move_all_total: int = 0
        self._move_all_running: bool = False

    def _add_files(self) -> None:
        # Filtre "Tous les fichiers" en premier : evite que le picker filtre
        # silencieusement les .heic ou autres formats par defaut.
        files, _ = QFileDialog.getOpenFileNames(
            self, "Ajouter des fichiers a trier",
            "",
            "Tous les fichiers (*);;Fichiers supportes (*.jpg *.jpeg *.png *.bmp *.webp *.heic *.tiff *.gif *.pdf *.docx *.xlsx *.mp4 *.mov *.mkv *.avi *.webm)"
        )
        if not files:
            return

        # Diagnostic : on compte ce que Qt nous donne vs ce qu'on ajoute
        n_returned_by_qt = len(files)
        n_added = 0
        n_already_in_list = 0
        n_path_error = 0
        examples_skipped: list[str] = []

        for f in files:
            try:
                p = Path(f)
            except Exception:  # noqa: BLE001
                n_path_error += 1
                continue
            if p in self.sources:
                n_already_in_list += 1
                if len(examples_skipped) < 3:
                    examples_skipped.append(p.name)
                continue
            self.sources.append(p)
            QListWidgetItem(f"[fichier] {p.name}    -    {p.parent}", self.sources_list)
            n_added += 1

        # Si y a une perte (Qt a renvoye moins ou on a deduplique), on previent
        # l'user avec un message clair. Sinon, silencieux.
        n_lost = n_returned_by_qt - n_added
        if n_lost > 0:
            details = []
            if n_already_in_list > 0:
                ex = ", ".join(examples_skipped)
                details.append(f"• {n_already_in_list} deja dans la liste (ex: {ex})")
            if n_path_error > 0:
                details.append(f"• {n_path_error} avec un chemin invalide")
            details_txt = "\n".join(details) if details else "(cause inconnue)"
            QMessageBox.information(
                self,
                "Quelques fichiers ignores",
                f"Windows m'a envoye {n_returned_by_qt} fichier(s), "
                f"j'en ai ajoute {n_added} a la liste.\n\n"
                f"Les {n_lost} restant(s) ont ete ignores :\n{details_txt}\n\n"
                f"Si t'attendais plus de fichiers que ce que Windows m'a envoye, "
                f"c'est probablement que Windows a tronque la selection multiple "
                f"(buffer interne limite). Pour les gros volumes, utilise plutot "
                f"'Ajouter dossier...'."
            )

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
            # Met a jour les suggestions d'autocomplete avec les sous-dossiers
            # existants dans cette racine (utile si l'user a deja un dossier
            # 'Plage', 'Famille', etc. et veut y deposer des photos).
            self._refresh_known_folders_with_dest()

    def _scan_dest_subfolders(self) -> list[str]:
        """Liste les sous-dossiers de 1er niveau de la racine de classement
        (ou des sources si pas de racine explicite). Sert a alimenter
        l'autocomplete avec les dossiers DEJA EXISTANTS.
        """
        roots: list[Path] = []
        if self._dest_root is not None:
            roots.append(self._dest_root)
        else:
            # Fallback : utilise les sources qui sont des dossiers
            for s in self.sources:
                if s.is_dir():
                    roots.append(s)
        names: set[str] = set()
        for root in roots:
            try:
                for d in root.iterdir():
                    if d.is_dir() and not d.name.startswith("."):
                        names.add(d.name)
            except OSError:
                continue
        return sorted(names)

    def _refresh_known_folders_with_dest(self) -> None:
        """Refresh la liste known_folders en ajoutant les sous-dossiers
        existants de la racine de classement. Met a jour les cards visibles.
        """
        existing = self._scan_dest_subfolders()
        if not existing:
            return
        before = set(self._known_folders_cache)
        merged = sorted(before | set(existing))
        if merged == self._known_folders_cache:
            return
        self._known_folders_cache = merged
        # Update les cards deja visibles (si y en a)
        for c in self.cards:
            try:
                c.update_known_folders(self._known_folders_cache)
            except Exception:  # noqa: BLE001
                pass

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
                # Fichier ajoute explicitement par l'user : on l'inclut toujours
                # (meme si extension exotique). cluster_files le mettra en
                # singleton 'other' si pas d'embedding possible.
                candidates.append(s)
            elif s.is_dir():
                if self.recursive_cb.isChecked():
                    src_files = [p for p in s.rglob("*") if p.is_file()]
                else:
                    src_files = [p for p in s.iterdir() if p.is_file()]
                # Pour les dossiers, on filtre par extensions supportees pour
                # eviter d'aspirer des centaines de fichiers systeme/programmes.
                # L'user peut ajouter explicitement un fichier exotique via
                # 'Ajouter fichiers...' s'il en veut un specifique.
                src_files = [p for p in src_files if p.suffix.lower() in SUPPORTED_EXTS]
                candidates.extend(src_files)
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

        # Stocke pour pouvoir re-clusteriser plus tard ("Elargir") sans rescan
        self._last_clustered_paths = list(files)

        self._thread = QThread(self)
        if mode == "local":
            threshold = self.sim_slider.value() / 100.0
            self._last_used_threshold = threshold
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

    PAGE_SIZE = 30  # Anti-crash : limite le nb de cartes rendues en RAM

    def _on_clustering_done(self, clusters: list) -> None:
        self.progress.setVisible(False)
        self.analyze_btn.setEnabled(True)
        if not clusters:
            self._empty_lbl.setVisible(True)
            self._empty_lbl.setText(t("sort.cluster_none"))
            self.footer.setText(t("sort.footer_zero"))
            self.progress_label.setText(t("sort.cluster_none"))
            QMessageBox.information(self, t("sort.cluster_done_title"), t("sort.cluster_none_popup"))
            return
        known = [f for f, _ in sort.load_known_folders()]
        if embeddings.embeddings_available():
            store = exemplars.ExemplarStore.get()
            known = sorted(set(known) | set(store.known_folders()))
        # Ajoute aussi les sous-dossiers DEJA EXISTANTS dans la racine de
        # classement (= si l'user a deja un dossier 'Plage' ou 'Famille',
        # on le propose en autocomplete pour qu'il puisse y rajouter sans
        # avoir a retaper le nom exact).
        existing_dest = self._scan_dest_subfolders()
        if existing_dest:
            known = sorted(set(known) | set(existing_dest))

        self._pending_clusters = [c for c in clusters if c.size >= 1]
        self._rendered_count = 0
        self._known_folders_cache = known
        self._render_next_cluster_page()
        self.footer.setText(t("sort.footer_remaining", n=len(self._pending_clusters)))
        n = len(self._pending_clusters)
        self.progress_label.setText(t("sort.cluster_done", n=n))
        # Message popup pour confirmer la fin de l'analyse
        QMessageBox.information(
            self, t("sort.cluster_done_title"),
            t("sort.cluster_done_body", n=n)
        )
        # Affiche le bouton Retour si on a effectivement des groupes
        if self._pending_clusters:
            self.back_btn.setVisible(True)
            self.move_all_btn.setVisible(True)

    def _back_to_setup(self) -> None:
        """Efface les groupes et revient a l'etat initial de selection."""
        self._clear_cards()
        # Retire aussi le bouton "Afficher plus" s'il existe
        if hasattr(self, "_more_btn_clusters") and self._more_btn_clusters is not None:
            self._container_layout.removeWidget(self._more_btn_clusters)
            self._more_btn_clusters.deleteLater()
            self._more_btn_clusters = None
        self._pending_clusters = []
        self._rendered_count = 0
        self._empty_lbl.setVisible(True)
        self._empty_lbl.setText(t("sort.empty"))
        self.progress_label.setText("")
        self.footer.setText(t("sort.footer_zero"))
        self.back_btn.setVisible(False)
        self.move_all_btn.setVisible(False)
        self.move_singletons_btn.setVisible(False)

    def _render_next_cluster_page(self) -> None:
        """Rend la prochaine page de clusters. Anti-OOM."""
        if hasattr(self, "_more_btn_clusters") and self._more_btn_clusters is not None:
            self._container_layout.removeWidget(self._more_btn_clusters)
            self._more_btn_clusters.deleteLater()
            self._more_btn_clusters = None
        end = min(self._rendered_count + self.PAGE_SIZE, len(self._pending_clusters))
        for i in range(self._rendered_count, end):
            c = self._pending_clusters[i]
            card = ClusterCard(c, index=i + 1, known_folders=self._known_folders_cache)
            card.move_requested.connect(self._on_move_requested)
            card.recluster_loose_requested.connect(self._recluster_loose)
            self.cards.append(card)
            self._container_layout.insertWidget(self._container_layout.count() - 1, card)
        self._rendered_count = end
        remaining = len(self._pending_clusters) - self._rendered_count
        if remaining > 0:
            self._more_btn_clusters = QPushButton(
                f"Afficher {min(self.PAGE_SIZE, remaining)} groupes de plus ({remaining} restants)"
            )
            self._more_btn_clusters.setProperty("role", "secondary")
            self._more_btn_clusters.clicked.connect(self._render_next_cluster_page)
            self._container_layout.insertWidget(self._container_layout.count() - 1, self._more_btn_clusters)
        else:
            self._more_btn_clusters = None

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

        # Recupere le nom du dossier ou ce cluster a ete deplace (avant suppression)
        moved_folder_name: str | None = None
        card = self._find_card(cluster)
        if card is not None:
            moved_folder_name = card.folder_input.text().strip()

        # Retire la carte du cluster traite
        self._remove_card_for_cluster(cluster)
        self._update_footer()

        # Ajoute le dossier aux suggestions de TOUTES les autres cards : comme
        # ca le nom apparait en autocomplete immediatement pour les autres
        # groupes (avant on devait relancer Analyser).
        if moved_folder_name and moved_folder_name not in self._known_folders_cache:
            self._known_folders_cache = sorted(set(self._known_folders_cache) | {moved_folder_name})
            for c in self.cards:
                try:
                    c.update_known_folders(self._known_folders_cache)
                except Exception:  # noqa: BLE001
                    pass  # une card vieille / detruite, on ignore

        # Si plus aucun cluster, on continue la queue "Deplacer tout" eventuelle
        self._continue_move_all_if_running()

    def _cleanup_move_thread(self) -> None:
        if self._move_worker is not None:
            self._move_worker.deleteLater()
            self._move_worker = None
        if self._move_thread is not None:
            self._move_thread.deleteLater()
            self._move_thread = None

    # ==================================================================
    # Re-cluster plus permissif ("Elargir") : seuil -0.05 sur les memes paths
    # ==================================================================
    def _recluster_loose(self) -> None:
        """Re-lance le clustering local avec un seuil reduit de 0.05.

        N'a de sens qu'en mode local CLIP. Si on est en mode API, on previent
        l'user que ce n'est pas applicable.
        """
        if not self._last_clustered_paths:
            QMessageBox.information(
                self, "Pas de session",
                "Aucune analyse en cours a elargir. Lance d'abord une analyse."
            )
            return
        new_threshold = max(0.65, self._last_used_threshold - 0.05)
        if new_threshold >= self._last_used_threshold:
            QMessageBox.information(
                self, "Deja au minimum",
                "Le seuil est deja au minimum (0.65), impossible d'elargir plus. "
                "Au-dela, les groupes deviennent du n'importe quoi."
            )
            return

        ans = QMessageBox.question(
            self, "Elargir le regroupement",
            f"Re-lancer le clustering avec un seuil de {new_threshold:.2f} "
            f"(au lieu de {self._last_used_threshold:.2f}) ?\n\n"
            f"Les groupes vont fusionner. Tes noms de dossiers tapes seront "
            f"perdus puisqu'on rebuild les groupes.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        # Lance un nouveau ClusterWorker avec le seuil reduit sur les MEMES paths
        # (pas de rescan des sources, vu qu'elles ont pu etre videes).
        if not embeddings.embeddings_available():
            QMessageBox.critical(
                self, "Modeles indispo",
                "Modeles ONNX CLIP introuvables. Re-clustering impossible."
            )
            return

        self._clear_cards()
        self._empty_lbl.setVisible(False)
        self.progress.setVisible(True)
        self.progress.setRange(0, len(self._last_clustered_paths))
        self.progress_label.setText(f"Re-clusterisation (seuil {new_threshold:.2f})...")
        self.analyze_btn.setEnabled(False)
        self._last_used_threshold = new_threshold
        # Met aussi a jour le slider pour reflet visuel
        self.sim_slider.setValue(int(new_threshold * 100))

        self._thread = QThread(self)
        self._worker = ClusterWorker(list(self._last_clustered_paths), threshold=new_threshold)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_clustering_done)
        self._worker.failed.connect(self._on_clustering_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._thread.start()

    # ==================================================================
    # Bouton global "Deplacer TOUS les groupes nommes"
    # ==================================================================
    def _start_move_all(self) -> None:
        """Construit la queue des clusters a deplacer et lance le 1er.

        Inclut uniquement les clusters dont le folder_input n'est pas vide.
        Les autres sont laisses tels quels (l'user devra les traiter / skipper
        a la main).
        """
        if self._move_all_running:
            QMessageBox.information(
                self, "Deja en cours",
                "Le deplacement de masse est deja en cours, patiente."
            )
            return
        queue: list = []
        for c in list(self.cards):
            name = c.folder_input.text().strip()
            if name:
                queue.append((c.cluster, name))
        if not queue:
            QMessageBox.information(
                self, "Aucun groupe nomme",
                "Aucun groupe n'a de nom de dossier saisi. Tape un nom dans au "
                "moins un groupe avant de lancer 'Deplacer TOUS'."
            )
            return
        # Confirmation
        ans = QMessageBox.question(
            self, "Confirmation",
            f"Deplacer {len(queue)} groupe(s) maintenant ?\n\n"
            f"Les groupes seront traites en sequence, un par un. "
            f"Tu peux suivre la progression dans la barre.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._move_all_queue = queue
        self._move_all_total = len(queue)
        self._move_all_running = True
        self.move_all_btn.setEnabled(False)
        self._process_next_in_move_all()

    def _process_next_in_move_all(self) -> None:
        """Depile et lance le prochain move de la queue. Si vide, finit."""
        if not self._move_all_queue:
            # Termine
            done = self._move_all_total
            self._move_all_running = False
            self._move_all_total = 0
            self.move_all_btn.setEnabled(True)
            self.move_singletons_btn.setEnabled(True)
            # Vide la liste des sources : les fichiers sont deplaces, garder
            # ces chemins n'a aucun sens (et certains pointent vers du vide).
            self._clear_sources()
            QMessageBox.information(
                self, "Termine",
                f"[FINI] {done} groupe(s) deplaces.\n\n"
                f"La liste des sources a ete videe automatiquement. "
                f"Tu peux ajouter de nouveaux fichiers/dossiers pour un autre tri."
            )
            return
        cluster, name = self._move_all_queue.pop(0)
        progress_idx = self._move_all_total - len(self._move_all_queue)
        self.progress_label.setText(
            f"Deplacement {progress_idx} / {self._move_all_total} : {name}..."
        )
        # Re-utilise le flux normal d'un seul move
        self._on_move_requested(cluster, name)

    def _continue_move_all_if_running(self) -> None:
        """Appele depuis _on_cluster_moved pour enchainer si on est en mode 'tout'."""
        if self._move_all_running:
            # Petit delai pour laisser le thread precedent se nettoyer proprement
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(100, self._process_next_in_move_all)

    # ==================================================================
    # Singleton handler : deplacer tous les fichiers isoles dans un album commun
    # ==================================================================
    def _move_all_singletons(self) -> None:
        """Trouve tous les clusters de taille 1 et les deplace ensemble dans
        un meme dossier (par defaut 'Autres', modifiable par l'user).
        """
        singletons = [c for c in self.cards if c.cluster.size == 1]
        if len(singletons) < 2:
            QMessageBox.information(
                self, "Pas d'isoles",
                "Il n'y a pas (ou plus) d'isoles a regrouper."
            )
            return

        # Demande le nom du dossier "Autres"
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            self, "Album commun pour les isoles",
            f"Nom du dossier pour les {len(singletons)} fichier(s) isole(s) :",
            text="Autres",
        )
        if not ok or not name.strip():
            return
        folder_name = name.strip()

        # Confirme
        ans = QMessageBox.question(
            self, "Deplacer les isoles",
            f"Deplacer {len(singletons)} fichier(s) isole(s) vers le dossier "
            f"'{folder_name}' ?\n\nLes groupes a 2+ fichiers ne sont pas touches.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return

        # Reutilise la queue _move_all_queue pour traiter les singletons en
        # sequence (chacun est techniquement un cluster d'1 fichier).
        if self._move_all_running:
            QMessageBox.information(
                self, "Deja en cours",
                "Un deplacement de masse est deja en cours, patiente."
            )
            return

        # Met le nom dans le folder_input de chaque singleton (pour que les
        # autres mecanismes - autocomplete, etc. - se mettent a jour)
        for c in singletons:
            c.folder_input.setText(folder_name)

        queue = [(c.cluster, folder_name) for c in singletons]
        self._move_all_queue = queue
        self._move_all_total = len(queue)
        self._move_all_running = True
        self.move_singletons_btn.setEnabled(False)
        self.move_all_btn.setEnabled(False)
        self._process_next_in_move_all()

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
            self.footer.setText(t("sort.all_done"))
            self._empty_lbl.setVisible(True)
            self._empty_lbl.setText(t("sort.all_done"))
            self.move_all_btn.setVisible(False)
            self.move_singletons_btn.setVisible(False)
        else:
            n_singletons = sum(1 for c in self.cards if c.cluster.size == 1)
            if n_singletons:
                self.footer.setText(t("sort.footer_with_iso", n=len(self.cards), iso=n_singletons))
            else:
                self.footer.setText(t("sort.footer_remaining", n=len(self.cards)))
            self.move_all_btn.setVisible(True)
            self.move_singletons_btn.setVisible(n_singletons >= 2)
            if n_singletons >= 2:
                self.move_singletons_btn.setText(t("sort.move_singletons", n=n_singletons))

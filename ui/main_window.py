"""Fenetre principale : 2 onglets, Dedup et Tri + selecteur de langue."""

from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel, QHBoxLayout,
    QComboBox, QMessageBox,
)

from core import i18n
from core.i18n import t

from .styles import QSS
from .dedup_view import DedupView
from .cluster_view import ClusterView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(t("main.window_title"))
        self.setMinimumSize(900, 600)
        self.setStyleSheet(QSS)

        tabs = QTabWidget(self)
        tabs.addTab(DedupView(self), t("main.tab_dedup"))
        tabs.addTab(ClusterView(self), t("main.tab_sort"))

        # Selecteur de langue dans le coin haut-droite des onglets
        lang_widget = QWidget()
        lang_layout = QHBoxLayout(lang_widget)
        lang_layout.setContentsMargins(8, 0, 8, 0)
        lang_layout.setSpacing(4)
        lang_label = QLabel(t("main.lang_label"))
        lang_layout.addWidget(lang_label)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Francais", "fr")
        self.lang_combo.addItem("English", "en")
        current = i18n.get_lang()
        idx = 0 if current == "fr" else 1
        self.lang_combo.setCurrentIndex(idx)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_layout.addWidget(self.lang_combo)
        tabs.setCornerWidget(lang_widget, Qt.Corner.TopRightCorner)

        self.setCentralWidget(tabs)

    def _on_lang_changed(self, idx: int) -> None:
        new_lang = self.lang_combo.itemData(idx)
        if new_lang == i18n.get_lang():
            return
        i18n.set_lang(new_lang)
        QMessageBox.information(
            self, t("main.lang_changed"), t("main.lang_restart")
        )

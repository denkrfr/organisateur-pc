"""Fenetre principale : 2 onglets, Dedup et Tri."""

from __future__ import annotations
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QMainWindow, QTabWidget, QWidget, QVBoxLayout, QLabel

from .styles import QSS
from .dedup_view import DedupView
from .cluster_view import ClusterView


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Organisateur — Doublons & Tri par ressemblance")
        self.setMinimumSize(900, 600)
        self.setStyleSheet(QSS)

        tabs = QTabWidget(self)
        tabs.addTab(DedupView(self), "Doublons")
        tabs.addTab(ClusterView(self), "Tri")
        self.setCentralWidget(tabs)

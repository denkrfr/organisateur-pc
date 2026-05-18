"""Dialog pour choisir le mode de tri : Local CLIP ou IA cloud.

Affiche les 2 options avec leurs trade-offs (vitesse vs privacy) et le statut
de configuration cloud (si une cle est deja stockee).
"""

from __future__ import annotations
from typing import Optional, Literal

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QMessageBox,
)

from core import api_key_store as ks
from .styles import TEXT, TEXT2, TEXT3, CARD, BORDER, ACCENT, ACCENT2, OK


TriMode = Literal["local", "api"]


class TriModeDialog(QDialog):
    """Dialog modal au lancement d'une analyse. Apres exec() :
      - self.chosen_mode = "local" ou "api" si OK
      - None si Annule
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Mode de tri")
        self.setMinimumSize(560, 480)
        self.chosen_mode: Optional[TriMode] = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Comment veux-tu trier tes photos ?")
        title.setStyleSheet(f"color: {TEXT}; font-size: 18px; font-weight: 800;")
        layout.addWidget(title)

        # === Mode local ===
        local_card = QFrame()
        local_card.setStyleSheet(
            f"QFrame {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: 8px; padding: 14px; }}"
        )
        lcl = QVBoxLayout(local_card)
        head = QHBoxLayout()
        icon = QLabel("🔒")
        icon.setStyleSheet("font-size: 24px;")
        head.addWidget(icon)
        col = QVBoxLayout()
        t = QLabel("Mode local (CLIP)")
        t.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: 700;")
        col.addWidget(t)
        tag = QLabel("100% PRIVE")
        tag.setStyleSheet(f"color: {OK}; font-size: 11px; font-weight: 700;")
        col.addWidget(tag)
        head.addLayout(col)
        head.addStretch()
        lcl.addLayout(head)
        d = QLabel(
            "Aucune photo ne quitte ton PC. Modele IA local (CLIP, ~150 Mo deja "
            "embarque dans l'app). Tourne sur le CPU.\n\n"
            "Regroupe par ressemblance visuelle (memes couleurs, formes, scenes). "
            "Plus lent (~0.5 sec par photo), plus restrictif sur les criteres."
        )
        d.setStyleSheet(f"color: {TEXT2}; font-size: 12px;")
        d.setWordWrap(True)
        lcl.addWidget(d)
        local_btn = QPushButton("Utiliser le mode local")
        local_btn.clicked.connect(self._choose_local)
        lcl.addWidget(local_btn)
        layout.addWidget(local_card)

        # === Mode API ===
        api_card = QFrame()
        api_card.setStyleSheet(
            f"QFrame {{ background: {CARD}; border: 2px solid {ACCENT}; "
            f"border-radius: 8px; padding: 14px; }}"
        )
        acl = QVBoxLayout(api_card)
        head2 = QHBoxLayout()
        icon2 = QLabel("☁")
        icon2.setStyleSheet("font-size: 24px;")
        head2.addWidget(icon2)
        col2 = QVBoxLayout()
        t2 = QLabel("Mode IA cloud")
        t2.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: 700;")
        col2.addWidget(t2)
        tag2 = QLabel("RAPIDE & MALIN")
        tag2.setStyleSheet(f"color: {ACCENT2}; font-size: 11px; font-weight: 700;")
        col2.addWidget(tag2)
        head2.addLayout(col2)
        head2.addStretch()
        acl.addLayout(head2)
        d2 = QLabel(
            "Tes photos sont envoyees a Google Gemini ou OpenAI GPT-5 nano pour "
            "analyse. Plus rapide et plus precis, regroupe par THEME (plage, "
            "repas, captures de cours, animaux, documents...) et te propose un "
            "nom d'album pour chaque groupe.\n\n"
            "Necessite une cle API (gratuite pour Gemini)."
        )
        d2.setStyleSheet(f"color: {TEXT2}; font-size: 12px;")
        d2.setWordWrap(True)
        acl.addWidget(d2)

        # Statut config
        configured = ks.get_configured_provider()
        if configured:
            label_map = {
                "gemini": "Google Gemini (gratuit)",
                "gemini-paid": "Google Gemini (privee)",
                "openai": "OpenAI GPT-5 nano",
            }
            cfg = QLabel(f"✓ Configure : {label_map.get(configured, configured)}")
            cfg.setStyleSheet(f"color: {OK}; font-size: 12px; font-weight: 600;")
            acl.addWidget(cfg)

        api_btn = QPushButton("Utiliser le mode IA cloud")
        api_btn.clicked.connect(self._choose_api)
        acl.addWidget(api_btn)

        if configured:
            reset_btn = QPushButton("Reset cle API")
            reset_btn.setProperty("role", "secondary")
            reset_btn.clicked.connect(self._reset_api)
            acl.addWidget(reset_btn)

        layout.addWidget(api_card)
        layout.addStretch()

        row = QHBoxLayout()
        row.addStretch()
        cancel = QPushButton("Annuler")
        cancel.setProperty("role", "secondary")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        layout.addLayout(row)

    def _choose_local(self) -> None:
        self.chosen_mode = "local"
        self.accept()

    def _choose_api(self) -> None:
        # Si pas configure, lance le wizard
        if not ks.get_configured_provider():
            from .api_setup_dialog import ApiSetupDialog
            dlg = ApiSetupDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted:
                return
            if not dlg.configured_provider:
                return
        self.chosen_mode = "api"
        self.accept()

    def _reset_api(self) -> None:
        ans = QMessageBox.question(
            self, "Reset cle API",
            "Supprimer la cle API stockee ? Tu devras la re-saisir au prochain "
            "usage du mode IA cloud.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        ks.reset_all()
        # Refresh : ferme et rouvre
        QMessageBox.information(self, "Reset", "Cle API supprimee.")
        self.reject()  # ferme, l'user re-clic Analyser pour reouvrir

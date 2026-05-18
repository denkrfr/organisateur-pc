"""Wizard 3 etapes pour configurer le mode IA cloud :
  1. Disclosure : tes photos vont sortir du PC, lis les ToS, accepte ou refuse
  2. Provider : choisir Gemini gratuit / Gemini privee / OpenAI GPT-5 nano
  3. Cle : coller la cle API, validation soft du format, stocker chiffre DPAPI

A la fin, retourne le ProviderId choisi (ou None si Annule).
"""

from __future__ import annotations
import re
from typing import Optional

from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QFrame, QStackedWidget, QWidget, QMessageBox, QScrollArea,
)

from core import api_key_store as ks
from .styles import (
    TEXT, TEXT2, TEXT3, CARD, CARD2, BORDER, ACCENT, ACCENT2, OK, WARN, DANGER,
)


GEMINI_KEY_URL = "https://aistudio.google.com/apikey"
GEMINI_BILLING_URL = "https://ai.google.dev/gemini-api/docs/billing"
OPENAI_KEY_URL = "https://platform.openai.com/api-keys"
GEMINI_PRIVACY = "https://ai.google.dev/gemini-api/terms"
OPENAI_PRIVACY = "https://openai.com/policies/api-data-usage-policies"


def _looks_like_gemini(k: str) -> bool:
    return bool(re.match(r"^AIza[\w-]{30,}$", k))


def _looks_like_openai(k: str) -> bool:
    return bool(re.match(r"^sk-[\w-]{20,}$", k))


class ApiSetupDialog(QDialog):
    """Wizard de configuration du mode IA cloud.

    Apres exec(), si accept(), `self.configured_provider` contient le provider
    configure. Sinon None.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Configuration du mode IA cloud")
        self.setMinimumSize(640, 580)
        self.configured_provider: Optional[ks.ProviderId] = None
        self._selected_provider: ks.ProviderId = "gemini"
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_disclosure())
        self.stack.addWidget(self._build_provider())
        self.stack.addWidget(self._build_key())
        layout.addWidget(self.stack)

    # ==================================================================
    # Etape 1 : Disclosure
    # ==================================================================
    def _build_disclosure(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Mode IA cloud")
        title.setStyleSheet(f"color: {TEXT}; font-size: 20px; font-weight: 800;")
        outer.addWidget(title)

        body = QLabel(
            "Cette option utilise un service d'IA en ligne (Google Gemini ou OpenAI "
            "GPT-5 nano) pour trier tes photos par theme. Le tri est plus rapide et "
            "plus precis qu'avec le mode local, et l'IA propose elle-meme des noms "
            "d'albums."
        )
        body.setStyleSheet(f"color: {TEXT}; font-size: 13px;")
        body.setWordWrap(True)
        outer.addWidget(body)

        warn = QFrame()
        warn.setStyleSheet(
            f"QFrame {{ background: rgba(255, 212, 59, 0.1); border: 1px solid {WARN}; "
            f"border-radius: 6px; padding: 12px; }}"
        )
        wlay = QVBoxLayout(warn)
        wt = QLabel("⚠ Important sur la confidentialite")
        wt.setStyleSheet(f"color: {WARN}; font-weight: 700; font-size: 13px;")
        wlay.addWidget(wt)
        for txt in [
            "En utilisant ce mode, tes photos seront ENVOYEES a Google ou OpenAI "
            "pour analyse. Selon le fournisseur et le tier choisi, elles peuvent "
            "etre utilisees pour entrainer les modeles (notamment sur le tier "
            "gratuit de Gemini).",
            "👉 Lis TOUJOURS les conditions d'utilisation du fournisseur avant "
            "d'envoyer tes donnees. Les liens sont sur chaque carte de l'etape "
            "suivante.",
            "Pour rester 100% offline, retourne au mode local (CLIP).",
        ]:
            l = QLabel(txt)
            l.setStyleSheet(f"color: {TEXT}; font-size: 12px;")
            l.setWordWrap(True)
            wlay.addWidget(l)
        outer.addWidget(warn)
        outer.addStretch()

        row = QHBoxLayout()
        cancel = QPushButton("Annuler")
        cancel.setProperty("role", "secondary")
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)
        row.addStretch()
        cont = QPushButton("J'accepte, continuer")
        cont.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        row.addWidget(cont)
        outer.addLayout(row)
        return w

    # ==================================================================
    # Etape 2 : Choix provider
    # ==================================================================
    def _build_provider(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(20, 20, 20, 20)

        title = QLabel("Choisis ton fournisseur")
        title.setStyleSheet(f"color: {TEXT}; font-size: 20px; font-weight: 800;")
        outer.addWidget(title)

        self._provider_cards: dict[str, QFrame] = {}
        for pid, name, tag, tag_color, desc, links in [
            (
                "gemini",
                "Google Gemini Flash",
                "GRATUIT",
                OK,
                "Quota gratuit : 15 req/min, 1500/jour. Pour 200 photos ≈ 1 min "
                "d'analyse. Cle gratuite sur Google AI Studio.\n\n"
                "⚠ Tier gratuit : selon les conditions Google, tes photos peuvent "
                "etre utilisees pour entrainer leurs modeles.",
                [("📖 Lire les conditions Gemini", GEMINI_PRIVACY)],
            ),
            (
                "gemini-paid",
                "Google Gemini Flash (privee)",
                "PRIVE - BILLING ACTIVE",
                "#74b9ff",
                "Meme API que le tier gratuit, mais SI tu as active le billing sur "
                "ton projet Google Cloud, Google s'engage a NE PAS utiliser tes "
                "photos pour entrainer ses modeles.\n\n"
                "En pratique tu paies souvent 0$ tant que tu restes sous le quota "
                "gratuit, mais tu beneficies de la policy privacy du tier paye. A "
                "toi de verifier que ton projet a bien le billing actif.",
                [
                    ("💳 Activer le billing GCP", GEMINI_BILLING_URL),
                    ("📖 Conditions Gemini", GEMINI_PRIVACY),
                ],
            ),
            (
                "openai",
                "OpenAI GPT-5 nano",
                "PAYANT ~0,05$ / 1000 PHOTOS",
                WARN,
                "Le modele le moins cher d'OpenAI avec vision integree. Tres bonne "
                "qualite, lecture de scenes precise.\n\n"
                "Politique API OpenAI : tes photos ne sont pas utilisees pour "
                "entrainer leurs modeles par defaut. Compte OpenAI avec credits "
                "requis (5$ minimum, dure des mois en usage perso).",
                [("📖 Conditions OpenAI", OPENAI_PRIVACY)],
            ),
        ]:
            card = self._make_provider_card(pid, name, tag, tag_color, desc, links)
            self._provider_cards[pid] = card
            outer.addWidget(card)

        self._update_provider_selection()

        row = QHBoxLayout()
        back = QPushButton("Retour")
        back.setProperty("role", "secondary")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        row.addWidget(back)
        row.addStretch()
        nxt = QPushButton("Suite")
        nxt.clicked.connect(lambda: self.stack.setCurrentIndex(2) or self._refresh_step3_labels())
        row.addWidget(nxt)
        outer.addLayout(row)

        scroll.setWidget(w)
        return scroll

    def _make_provider_card(
        self,
        pid: str,
        name: str,
        tag: str,
        tag_color: str,
        desc: str,
        links: list[tuple[str, str]],
    ) -> QFrame:
        card = QFrame()
        card.setObjectName(f"providercard_{pid}")
        card.setStyleSheet(
            f"QFrame#providercard_{pid} {{ background: {CARD}; border: 1px solid {BORDER}; "
            f"border-radius: 8px; padding: 14px; }}"
        )
        lay = QVBoxLayout(card)

        title = QLabel(name)
        title.setStyleSheet(f"color: {TEXT}; font-size: 15px; font-weight: 700;")
        lay.addWidget(title)
        tag_lbl = QLabel(tag)
        tag_lbl.setStyleSheet(f"color: {tag_color}; font-size: 11px; font-weight: 700;")
        lay.addWidget(tag_lbl)
        d = QLabel(desc)
        d.setStyleSheet(f"color: {TEXT2}; font-size: 12px;")
        d.setWordWrap(True)
        lay.addWidget(d)
        for label, url in links:
            btn = QPushButton(label)
            btn.setProperty("role", "secondary")
            btn.setStyleSheet(f"color: {ACCENT2}; text-align: left;")
            btn.clicked.connect(lambda _, u=url: QDesktopServices.openUrl(QUrl(u)))
            lay.addWidget(btn)

        # Bouton "Selectionner ce provider" en dernier
        sel = QPushButton(f"Selectionner")
        sel.clicked.connect(lambda _, p=pid: self._select_provider(p))
        lay.addWidget(sel)
        return card

    def _select_provider(self, pid: str) -> None:
        self._selected_provider = pid  # type: ignore[assignment]
        self._update_provider_selection()

    def _update_provider_selection(self) -> None:
        for pid, card in self._provider_cards.items():
            if pid == self._selected_provider:
                card.setStyleSheet(
                    f"QFrame {{ background: {CARD}; border: 2px solid {ACCENT}; "
                    f"border-radius: 8px; padding: 14px; }}"
                )
            else:
                card.setStyleSheet(
                    f"QFrame#providercard_{pid} {{ background: {CARD}; border: 1px solid {BORDER}; "
                    f"border-radius: 8px; padding: 14px; }}"
                )

    # ==================================================================
    # Etape 3 : Cle API
    # ==================================================================
    def _build_key(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(20, 20, 20, 20)

        self._key_title = QLabel("Cle API")
        self._key_title.setStyleSheet(f"color: {TEXT}; font-size: 20px; font-weight: 800;")
        outer.addWidget(self._key_title)

        self._key_body = QLabel("")
        self._key_body.setStyleSheet(f"color: {TEXT}; font-size: 13px;")
        self._key_body.setWordWrap(True)
        outer.addWidget(self._key_body)

        self._key_link_btn = QPushButton("Ouvrir la page de creation de cle ↗")
        self._key_link_btn.setProperty("role", "secondary")
        self._key_link_btn.setStyleSheet(f"color: {ACCENT2};")
        self._key_link_btn.clicked.connect(self._open_key_url)
        outer.addWidget(self._key_link_btn)

        lbl = QLabel("Cle API (copie-colle depuis la page) :")
        lbl.setStyleSheet(f"color: {TEXT}; font-size: 12px; margin-top: 12px;")
        outer.addWidget(lbl)

        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setStyleSheet(
            f"background: {CARD2}; color: {TEXT}; border: 1px solid {BORDER}; "
            f"border-radius: 4px; padding: 8px; font-family: monospace;"
        )
        outer.addWidget(self._key_input)

        help_lbl = QLabel(
            "La cle est chiffree localement via Windows DPAPI (CryptProtectData). "
            "Seul ton compte Windows peut la dechiffrer. Tu peux la supprimer plus "
            "tard depuis les parametres."
        )
        help_lbl.setStyleSheet(f"color: {TEXT3}; font-size: 11px; font-style: italic;")
        help_lbl.setWordWrap(True)
        outer.addWidget(help_lbl)
        outer.addStretch()

        row = QHBoxLayout()
        back = QPushButton("Retour")
        back.setProperty("role", "secondary")
        back.clicked.connect(lambda: self.stack.setCurrentIndex(1))
        row.addWidget(back)
        row.addStretch()
        save = QPushButton("Enregistrer et terminer")
        save.clicked.connect(self._handle_save)
        row.addWidget(save)
        outer.addLayout(row)
        return w

    def _refresh_step3_labels(self) -> None:
        p = self._selected_provider
        is_gemini = p in ("gemini", "gemini-paid")
        suffix = " (privee)" if p == "gemini-paid" else ""
        self._key_title.setText(f"Cle API {'Gemini' if is_gemini else 'OpenAI'}{suffix}")
        body = (
            f"1. Va sur la page de creation de cle de "
            f"{'Google AI Studio' if is_gemini else 'OpenAI Platform'}.\n"
            f"2. Cree une cle ({'gratuit pour Gemini' if is_gemini else 'compte OpenAI avec credits'}).\n"
            f"3. Copie-la et colle-la ci-dessous."
        )
        if p == "gemini-paid":
            body += (
                "\n4. IMPORTANT : verifie que le billing est ACTIF sur ton projet "
                "Google Cloud (sinon, c'est la policy gratuite qui s'applique)."
            )
        self._key_body.setText(body)
        self._key_input.setPlaceholderText("AIza..." if is_gemini else "sk-...")

    def _open_key_url(self) -> None:
        p = self._selected_provider
        url = GEMINI_KEY_URL if p in ("gemini", "gemini-paid") else OPENAI_KEY_URL
        QDesktopServices.openUrl(QUrl(url))

    def _handle_save(self) -> None:
        key = self._key_input.text().strip()
        if not key:
            QMessageBox.information(self, "Cle vide", "Colle ta cle API avant de continuer.")
            return
        p = self._selected_provider
        is_gemini = p in ("gemini", "gemini-paid")
        valid = _looks_like_gemini(key) if is_gemini else _looks_like_openai(key)
        if not valid:
            expected = "AIza..." if is_gemini else "sk-..."
            ans = QMessageBox.question(
                self,
                "Format de cle inhabituel",
                f"La cle ne commence pas par \"{expected}\" ou est trop courte. "
                "Tu l'as peut-etre mal copiee (espace, BOM, coupure).\n\n"
                "Continuer quand meme ?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        try:
            ks.save_api_key(p, key)
            ks.save_selected_provider(p)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, "Erreur stockage", str(e))
            return
        self.configured_provider = p
        self.accept()

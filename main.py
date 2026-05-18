"""Entry point — lance l'app PyQt6.

Usage :
    python main.py

Pour builder un .exe :
    pip install pyinstaller
    pyinstaller --onefile --windowed --name Organisateur main.py
"""

from __future__ import annotations
import sys

# Hardening Pillow (decompression bomb -> exception) - DOIT etre importe
# AVANT toute autre lib qui touche Pillow (PIL.Image).
from core import bootstrap  # noqa: F401

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Organisateur")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

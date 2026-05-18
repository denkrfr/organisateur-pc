"""Smoke test : importe tous les modules de l'app et construit MainWindow
sans afficher. Verifie que rien ne plante a l'instanciation des widgets.
A lancer avec :  ./.venv/Scripts/python.exe smoke_test.py
"""

from __future__ import annotations
import sys


def main() -> int:
    print("[1/4] Import des modules core...", flush=True)
    from core import models, dedup, sort
    print("       core.models OK")
    print("       core.dedup OK")
    print("       core.sort OK")

    print("[2/4] Import PyQt6 + ui...", flush=True)
    from PyQt6.QtWidgets import QApplication
    from ui.main_window import MainWindow
    from ui.dedup_view import DedupView
    from ui.sort_view import SortView, FolderPickerDialog
    print("       PyQt6 OK, ui.* OK")

    print("[3/4] Construction QApplication + MainWindow...", flush=True)
    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    print("       MainWindow OK, taille =", win.size().width(), "x", win.size().height())

    print("[4/4] Tests rapides core/sort heuristique...", flush=True)
    print("       OCR available :", sort._ocr_available())
    print("       known folders cached :", sort.load_known_folders())
    print("       known rules :", sort.load_learned_rules())

    print("\nSMOKE TEST OK", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

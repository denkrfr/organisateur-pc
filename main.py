"""Entry point — lance l'app PyQt6.

Usage :
    python main.py

Pour builder un .exe :
    pip install pyinstaller
    pyinstaller --onefile --windowed --name Organisateur main.py
"""

from __future__ import annotations
import sys
import traceback
from pathlib import Path

# Hardening Pillow (decompression bomb -> exception) - DOIT etre importe
# AVANT toute autre lib qui touche Pillow (PIL.Image).
from core import bootstrap  # noqa: F401

from PyQt6.QtWidgets import QApplication

from ui.main_window import MainWindow


# Fichier de log pour les exceptions non-attrapees. Si l'app crashe, on a
# au moins une trace ecrite quelque part au lieu d'une fermeture silencieuse.
_CRASH_LOG = Path.home() / ".organisateur-pc" / "crash.log"


def _global_exception_hook(exc_type, exc_value, exc_tb) -> None:
    """Hook global : log les exceptions Python non-attrapees au lieu de
    laisser Qt fermer l'app en silence. Affiche aussi une popup d'erreur.
    """
    # Ecriture du log
    try:
        _CRASH_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _CRASH_LOG.open("a", encoding="utf8") as f:
            from datetime import datetime
            f.write(f"\n=== {datetime.now().isoformat()} ===\n")
            traceback.print_exception(exc_type, exc_value, exc_tb, file=f)
    except Exception:  # noqa: BLE001
        pass  # peut pas ecrire le log, tant pis

    # Popup d'erreur (si Qt est encore alive)
    try:
        from PyQt6.QtWidgets import QMessageBox
        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))[-2000:]
        QMessageBox.critical(
            None, "Erreur inattendue",
            f"Quelque chose a plante mais l'app reste ouverte.\n\n"
            f"Detail (log dans {_CRASH_LOG}) :\n\n{msg}"
        )
    except Exception:  # noqa: BLE001
        # Print fallback console
        traceback.print_exception(exc_type, exc_value, exc_tb)


def main() -> int:
    # Installe le hook global avant tout
    sys.excepthook = _global_exception_hook

    app = QApplication(sys.argv)
    app.setApplicationName("Organisateur")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

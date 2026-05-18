"""Hardening au demarrage : protection contre les fichiers crafted.

Importe ce module en premier (main.py) pour activer :
  - Pillow DecompressionBomb -> exception (pas juste warning)
  - Cap raisonnable sur la taille des images decoded
"""

from __future__ import annotations
import warnings

from PIL import Image


# Plafond raisonnable : 200 megapixels.
# Couvre largement les photos 100 MP (smartphones recents = 50 MP) et scans
# haute res, mais bloque les images crafted a 1 milliard de pixels.
Image.MAX_IMAGE_PIXELS = 200_000_000

# Convertit le warning Pillow en exception bloquante. Toutes les Image.open()
# de l'app sont deja entourees de try/except generique -> l'image suspecte est
# juste ignoree au lieu de faire exploser la RAM.
warnings.simplefilter("error", Image.DecompressionBombWarning)

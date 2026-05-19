## v1.1.6 — Fix crash dans le tri quand tu cliques "Voir / Modifier"

### Le bug

Tu m'as signalé : "fonction doublons parfait ! fonction tri a crash après avoir classer mes fichier, jai clique sur 'voir' et ca a crash."

Cause : le dialog "Voir / Modifier la sélection" chargeait **tous les thumbnails en synchrone** au moment de l'ouverture. Si un fichier était :
- corrompu / tronqué
- en HEIC (codec pas fiable sans plugin spécifique)
- trop gros (genre 50 Mpx, ça OOM facile)
- d'un format que Pillow lit mal

→ Pillow pouvait segfaulter au niveau C, et Python ne voit absolument rien (les `try/except` Python n'attrapent pas les segfaults C). L'app se ferme net.

### Le fix

**1. `load_thumbnail` durci :**
- Skip pur et simple des fichiers > 25 Mo (évite OOM)
- Skip HEIC/HEIF (codec instable)
- Pour jpg/png/bmp/gif : utilise `QImageReader` (décodeur natif Qt en C++) au lieu de Pillow + ImageQt. C'est plus rapide ET plus stable.
- Pillow reste utilisé seulement en fallback pour WebP/TIFF.
- Catch aussi `MemoryError` (pas juste `Exception`).

**2. Dialog "Voir / Modifier" : chargement deferred :**
- Le dialog s'ouvre **instantanément** avec juste les noms de fichiers + cases à cocher.
- Les thumbnails se chargent ensuite une par une via `QTimer.singleShot`, sans bloquer l'event loop.
- Chaque chargement est isolé dans son propre try/except : si un fichier est mauvais, on saute juste celui-là, le reste continue.

### Installation

1. Télécharge `Organisateur-v1.1.6-portable-windows.zip` (~292 Mo)
2. Clic-droit → Extraire tout
3. Double-clic sur `Organisateur.exe`

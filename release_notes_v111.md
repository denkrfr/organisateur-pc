## Organisateur v1.1.1 — Fixes UX

### Doublons : sélection individuelle des fichiers

Avant : on voyait "2 fichiers + +5 autres", impossible de cocher individuellement quels supprimer.

Maintenant : **gros bouton "Voir / Modifier"** sur chaque groupe → ouvre une fenêtre avec **tous les fichiers** + thumbnails + **checkbox individuelle** sur chacun :
- Cocher = envoyer à la corbeille
- Décocher = garder
- Tag "LE + GROS" visible sur le plus volumineux (généralement la meilleure copie)
- Boutons rapides : "Cocher tout sauf le + gros" / "Tout cocher" / "Tout décocher"
- Cliquer une thumbnail = ouvre le fichier dans l'app par défaut (pour vérifier)

### Tri par ressemblance : pareil

Sur chaque groupe, **bouton textuel évident** "Voir / Modifier la sélection (X fichiers)" → ouvre la liste complète avec checkboxes individuelles pour décocher les intrus avant de déplacer.

### Anti-crash : pagination

Avant : si le scan trouvait 200+ groupes, l'app pouvait crasher (out of memory en rendant tous les widgets + thumbnails d'un coup).

Maintenant : **maximum 50 groupes affichés à la fois** (dedup) / **30** (tri). Bouton **"Afficher 50 de plus"** en bas pour continuer. Les groupes traités (déplacés/supprimés) libèrent la mémoire au fur et à mesure.

### Installation

1. Télécharge `Organisateur-v1.1.1-portable-windows.zip` (~292 Mo)
2. Clic-droit → Extraire tout
3. Double-clic sur `Organisateur.exe`

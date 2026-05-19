## v1.1.8 — Tri : auto-vide la liste après "Déplacer tout" + bordures égalisées

### Auto-vide la liste sources après Déplacer tout

Tu m'as dit : "après le déplacement ça reste dedans".

Effectivement, après que "Déplacer TOUS les groupes nommés" finisse, les chemins de fichiers/dossiers restaient dans la liste des sources alors que les fichiers eux-mêmes étaient déjà déplacés (donc la liste pointait dans le vide pour la moitié des entrées). Stupide.

Maintenant :
- À la fin du Déplacer tout → la liste des sources se vide automatiquement
- Le popup [FINI] te le dit clairement
- Tu peux ajouter de nouveaux fichiers/dossiers directement pour un autre tri

Le bouton "Vider" a aussi été renommé "**Vider la liste**" avec un tooltip explicite (ne touche pas aux fichiers sur disque, juste à la liste affichée).

### Bordure violette virée sur "Mode IA cloud"

Dans la fenêtre de choix Local / Cloud, la carte "Mode IA cloud" avait un cadre violet épais (2px ACCENT) alors que "Mode local" était en cadre neutre fin. Visuellement ça donnait l'impression que Cloud était "le bon choix" par défaut.

Maintenant les deux cards ont **exactement le même style** (1px BORDER neutre). À toi de choisir en lisant les descriptions, sans biais visuel.

### Installation

1. Télécharge `Organisateur-v1.1.8-portable-windows.zip` (~292 Mo)
2. Clic-droit → Extraire tout
3. Double-clic sur `Organisateur.exe`

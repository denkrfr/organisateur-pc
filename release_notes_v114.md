## v1.1.4 — Fix crash après corbeille + boutons Retour

### Le crash après envoi à la corbeille (fix important)

Tu m'as signalé : "jai envoye a la poubelle puis lapp sest ferme..."

Effectivement il y avait un crash qui pouvait arriver après l'envoi des fichiers à la corbeille, quand l'UI essayait de rafraîchir les groupes restants. Cause : une checkbox émettait un signal avec un index qui n'existait plus, et boom.

Deux protections ajoutées :
1. **`_send_checked_to_trash` en 3 phases distinctes** : d'abord la corbeille (opération système), puis la mise à jour UI dans un bloc try/except dédié, puis le message de confirmation. Si l'UI a un souci, les fichiers sont quand même dans la corbeille et tu reçois un avertissement clair (au lieu d'un crash).
2. **Bounds check sur les checkbox toggles** : si un index est hors-bornes (suite à une suppression), le signal est ignoré au lieu de planter.

Bonus : les groupes qui passent à < 2 fichiers sont maintenant proprement détachés du parent avant `deleteLater()` (évite des références zombies dans Qt).

### Boutons ← Retour sur les deux onglets

Quand tu lances un scan (Doublons ou Tri), les résultats prennent toute la place et tu n'avais aucun moyen évident d'effacer pour repartir sur un autre dossier. Fallait fermer/relancer.

Maintenant :
- Un bouton **← Retour** apparaît en haut à gauche dès qu'il y a des résultats.
- Clic dessus = ça efface les groupes affichés et tu retombes sur l'écran de sélection initial. Les fichiers sur disque ne sont pas touchés.

### Installation

1. Télécharge `Organisateur-v1.1.4-portable-windows.zip` (~292 Mo)
2. Clic-droit → Extraire tout
3. Double-clic sur `Organisateur.exe`

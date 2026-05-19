## v1.1.5 — Vraie fix du crash corbeille (worker thread + retour accueil)

### Le crash, vrai fix cette fois

Dans v1.1.4 j'avais essayé de rafraîchir l'UI après send2trash avec des try/except. Tu m'as dit que ça crashe encore. Vérification : Qt panique au niveau C++, le try/except Python le voit pas. Donc l'approche était condamnée.

**Le vrai fix**, c'est de **ne plus jamais toucher à l'UI en place après une suppression** :

1. **send2trash dans un thread séparé** (`TrashWorker` + QThread) — l'UI reste fluide pendant l'opération, et on n'a aucune manipulation Qt synchrone qui peut planter.
2. **Barre de progression** pendant la suppression : tu vois "X / N fichiers — nom_du_fichier_en_cours".
3. **Quand c'est fini** : popup "[FINI] X fichiers envoyés à la corbeille" + auto **retour à l'écran d'accueil** (les résultats sont effacés, plus aucune référence Qt à des fichiers supprimés).

C'est plus brutal qu'un refresh in-place, mais c'est **incassable** : on rebuild un état propre au lieu de patcher l'existant.

### Tri : message [FINI] clair après analyse

Quand l'analyse de tri se termine, t'avais pas vraiment d'indication claire que c'était fini. Maintenant :

- La barre de progression affiche "[FINI] X groupes formés — choisis un nom et clique Déplacer pour chaque."
- Une popup confirme avec le nombre de groupes formés et te rappelle quoi faire ensuite.

### Installation

1. Télécharge `Organisateur-v1.1.5-portable-windows.zip` (~292 Mo)
2. Clic-droit → Extraire tout
3. Double-clic sur `Organisateur.exe`

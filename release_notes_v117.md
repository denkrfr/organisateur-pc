## v1.1.7 — Tri : UX clarifiée + bouton "Déplacer TOUT"

### Tu m'as dit :

> "tu fais 'déplacer ce groupe' il te demande de cocher ou décocher puis tu valide et te dis de soit relance analyse soit clique déplacer groupe. C'est faux et nul."

Tu cliquais sur le bouton bleu prominent "Voir / Modifier la sélection (X fichiers)" en pensant que c'était "Déplacer". C'est lui qui ouvrait le dialog check/uncheck. Le vrai bouton "Déplacer ce groupe" était en style neutre, beaucoup moins visible. Source de confusion totale.

### Les 3 fixes

**1. Boutons clarifiés visuellement**
- **"Déplacer ce groupe"** est maintenant **le gros bouton bleu primaire** (c'est l'action principale, normal).
- L'ancien bouton "Voir / Modifier la sélection" devient "**Voir / décocher les intrus**" en style discret (bordure fine, transparent). C'est optionnel, sert juste à virer les fichiers qui n'ont rien à faire dans le groupe.

**2. Popup confus supprimé**
- Après avoir validé le dialog "Voir / décocher les intrus", il y avait un popup "Re-lance Analyser ou clique Déplacer pour appliquer". Plus aucun popup. Le compteur de fichiers se met à jour silencieusement sur la card. Tu vois le nouveau total et tu cliques Déplacer directement.

**3. Bouton "Déplacer TOUS les groupes nommés"**
- Un gros bouton vert en bas de la vue Tri.
- Tu remplis les noms de dossier pour chaque groupe, puis tu cliques **une seule fois** sur "Déplacer TOUS".
- Il déplace en séquence chaque groupe pour lequel t'as tapé un nom. Les groupes sans nom sont ignorés (tu les traiteras à la main).
- Progression "X / N : nom_du_dossier" pendant l'opération.
- Popup [FINI] à la fin.

**Bonus : l'autocomplete se met à jour en live**
- Avant : si tu déplaçais le groupe 1 vers "Plage", le nom "Plage" n'apparaissait pas dans les suggestions du groupe 2 tant que tu relançais pas l'analyse.
- Maintenant : dès qu'un move réussit, le nom est ajouté aux suggestions de **tous les autres groupes restants**. Plus besoin de relancer.

### Installation

1. Télécharge `Organisateur-v1.1.7-portable-windows.zip` (~292 Mo)
2. Clic-droit → Extraire tout
3. Double-clic sur `Organisateur.exe`

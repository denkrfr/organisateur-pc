## Organisateur v1.1.0 (Windows, portable)

### Nouveauté : Mode IA cloud (en option)

Au moment de cliquer "Analyser et regrouper" dans l'onglet Tri, tu choisis maintenant entre 2 modes :

🔒 **Local CLIP** (défaut, 100% privé)
Aucune photo ne quitte ton PC. Modèle IA embarqué. Regroupe par ressemblance visuelle.

☁ **IA cloud** (rapide & malin)
Tes photos sont envoyées à Google Gemini ou OpenAI GPT-5 nano. Regroupe par **thème** (plage, factures, captures de cours, animaux...) et propose un **nom d'album** automatiquement.

Wizard de setup intégré (3 étapes : avertissement privacy + choix provider + saisie clé API). Clé stockée chiffrée via Windows DPAPI (seul ton compte Windows peut la déchiffrer).

### 3 providers cloud au choix

| Provider | Coût | Privacy |
|---|---|---|
| **Google Gemini gratuit** | 1500 req/jour gratuit | Photos potentiellement utilisées pour entraîner |
| **Google Gemini privée** | Idem (billing GCP activé) | Google s'engage à NE PAS utiliser pour entraîner |
| **OpenAI GPT-5 nano** | ~0,05$ / 1000 photos | Non utilisées par défaut |

### Confidentialité

Le mode local reste le défaut. **Aucun appel réseau** n'est fait tant que tu n'as pas explicitement choisi le mode IA cloud + saisi ta clé API. Un avertissement clair t'informe avant le 1er envoi.

### Installation

1. Télécharge `Organisateur-v1.1.0-portable-windows.zip` (~292 Mo)
2. Clic-droit → Extraire tout
3. Double-clic sur `Organisateur.exe`

Pas d'installeur, pas d'antivirus à contourner. Comme un Notepad++ portable.

### Code source

https://github.com/denkrfr/organisateur-pc

# Organisateur PC

App Windows pour **dédupliquer** et **trier par ressemblance** ta bibliothèque
de fichiers (images + PDF + Word + Excel). Tourne **100 % en local**, zéro
appel réseau, zéro télémétrie.

L'IA visuelle (CLIP) est embarquée dans l'exécutable : pas de cloud, pas
d'API key, rien à configurer en plus.

---

## Ce que ça fait

### 1. Doublons
- Détecte les doublons **exacts** (byte-à-byte) sur images + PDF/Word/Excel
- Détecte les **quasi-doublons** : compressions WhatsApp, exports HEIC/JPG,
  screenshots avec timestamp différent, mêmes contenus de doc avec
  métadonnées différentes
- Pipeline : SHA256 partiel → byte-by-byte → perceptual hash (aHash 8×8) →
  fingerprint texte pour les docs
- Multi-thread : 8 workers en parallèle, gain mesuré **2.85x** vs séquentiel
- **Annulable** à tout moment (bouton Annuler pendant le scan)
- Action sûre : envoie à la **corbeille Windows** (`send2trash`), récupérable

### 2. Tri par ressemblance (IA visuelle)
- Regroupe automatiquement les fichiers qui se ressemblent visuellement,
  via embeddings **CLIP ViT-B/32** (quantized INT8, 85 Mo) tournant
  localement en CPU
- Compare aussi le texte des PDF/Word/Excel via **multilingual-e5-small**
  (130 Mo) pour matcher "facture" ≈ "invoice" ≈ "récépissé"
- Tu nommes chaque groupe une fois, l'app crée le dossier et déplace tout
- **Apprend de tes choix** : plus tu utilises, mieux ça classe automatiquement
- Slider pour ajuster la strictesse du regroupement (permissif ↔ très strict)

---

## Installation (recommandé : installer Windows)

1. Télécharge **`OrganisateurSetup.exe`** (~251 Mo) depuis le repo / le partage
2. Double-clique l'installeur
3. Suivez l'assistant (français, choisir dossier, créer icône bureau si tu veux)
4. Lance "Organisateur" depuis le menu Démarrer ou le bureau

Au premier lancement, l'app peut afficher un avertissement Windows
SmartScreen *"Windows a protégé votre PC"* — c'est normal pour un exe non
signé. Clic **"Plus d'infos"** → **"Exécuter quand même"** une seule fois.

### Désinstallation
Panneau de configuration → Applications → Organisateur → Désinstaller.
Les modèles et données utilisateur restent dans `~/.organisateur-pc/`,
tu peux les supprimer manuellement si tu veux.

---

## Utilisation

### Onglet Doublons
1. **Ajouter dossier** : un ou plusieurs dossiers à scanner
2. Coche **"Détecter aussi les quasi-doublons"** si tu veux les compressions
   et exports différents
3. **Scanner** → progress bar
4. Résultats en lignes horizontales : par groupe tu vois les thumbnails
   côte-à-côte + le chemin + tailles + % de match
5. Pour chaque groupe :
   - **Cocher sauf le + gros** (laisse le plus volumineux, supprime les copies)
   - Ou **Décocher** / cocher fichier par fichier en cliquant le chevron
6. **Envoyer à la corbeille système** → tu valides → c'est dans la corbeille
   Windows (récupérable)

### Onglet Tri par ressemblance
1. **+ Ajouter fichiers** ou **+ Ajouter dossier** : compose ta liste à trier
2. **Racine de classement** : où créer les sous-dossiers (par défaut = même
   que la source)
3. Optionnel : coche **"Ignorer icônes et fichiers système"** (filtre auto)
4. Ajuste la **strictesse** (slider) : plus strict = plus de petits groupes
   précis, plus permissif = moins de groupes
5. **Analyser et regrouper** → chaque fichier est embeddé en CLIP, clustering
   greedy par similarité cosinus
6. Pour chaque groupe :
   - Vois les 6 premières thumbnails + bouton `+N` pour voir tout
   - Tape un nom de dossier (autocomplete sur tes dossiers déjà utilisés)
   - Cliquer **Déplacer ce groupe** → le dossier est créé, les fichiers
     bougent, l'app apprend ces fichiers comme exemples du dossier

L'**apprentissage** : chaque déplacement nourrit le modèle. Au prochain
tri d'un dossier neuf, les fichiers similaires aux groupes déjà nommés
seront automatiquement classés (mais tu peux toujours utiliser le
clustering pur si tu préfères).

---

## Confidentialité

- **Zéro appel réseau** dans tout le code (vérifié par grep + audit runtime
  via `netstat`)
- **Zéro télémétrie** : aucun import de Firebase, Sentry, Mixpanel, etc.
- Modèles ML (CLIP + e5) **bundlés dans l'exe** : pas de download externe
- OCR Tesseract **local** (binaire Windows, pas d'API cloud)
- Données utilisateur stockées localement dans `~/.organisateur-pc/` :
  - `sort_folders.json` : noms de dossiers déjà utilisés (en clair —
    évite d'y mettre des noms sensibles)
  - `exemplars/*.npz` et `exemplars/*.json` : vecteurs d'embeddings
    (anonymes, non reconstructibles en image)
  - `embeddings/*.npy` : cache des vecteurs par fichier (clé = hash du
    path+mtime+size, pas le nom)
- **Aucun fichier source utilisateur n'est copié** dans le store (seuls
  des vecteurs numériques)
- Suppression **via corbeille Windows** (`send2trash`), récupérable

### Hardening
- Cap Pillow `MAX_IMAGE_PIXELS = 200M` + warning → exception
  (anti decompression bomb)
- Écriture atomique des données utilisateur (tmpfile + `os.replace`)
- Caches thread-safe (locks)
- `pickle` désactivé explicitement (`np.load(allow_pickle=False)`)

---

## Stack technique

- **Python 3.14** + **PyQt6** (UI native dark)
- **Pillow** + **numpy** (image processing)
- **imagehash** (perceptual hashing pour quasi-doublons)
- **pypdf** + **python-docx** + **openpyxl** (extraction texte docs)
- **pytesseract** (OCR via binaire Tesseract local)
- **onnxruntime** (inférence CLIP + e5 sur CPU)
- **tokenizers** (HF Rust tokenizer pour les modèles ONNX)
- **send2trash** (corbeille système Windows)
- **PyInstaller** (build exe `--onedir`)

### Modèles ML
- `Xenova/clip-vit-base-patch32` (vision + text quantized INT8, ~150 Mo)
- `Xenova/multilingual-e5-small` (text quantized INT8, ~130 Mo)
- Téléchargés depuis Hugging Face au build, **bundlés dans l'exe** (pas
  de DL au runtime côté utilisateur)

---

## Pour les développeurs

### Setup depuis les sources

```powershell
cd organisateur-pc
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### Lancer en mode dev

```powershell
.venv\Scripts\python.exe main.py
```

### Tesseract OCR (déjà bundlé pour l'utilisateur final, mais à installer
pour le dev local)

```powershell
winget install --id UB-Mannheim.TesseractOCR
```

L'app le détecte automatiquement à `C:\Program Files\Tesseract-OCR\` ou
via le `PATH`.

### Smoke tests

```powershell
.venv\Scripts\python.exe smoke_test.py
.venv\Scripts\python.exe smoke_test_pipeline.py
```

### Build de l'exe + installeur

```powershell
# 1. Build l'app en --onedir (dossier dans dist/Organisateur/)
.venv\Scripts\pyinstaller.exe --onedir --windowed --name "Organisateur" --noconfirm `
  --collect-submodules openpyxl --collect-submodules pypdf `
  --collect-submodules docx --collect-submodules onnxruntime `
  --collect-submodules tokenizers `
  --add-data "assets/models;assets/models" main.py

# 2. Compile l'installeur Windows avec Inno Setup
"C:\Users\USER\AppData\Local\Programs\Inno Setup 6\ISCC.exe" installer.iss

# Resultat : dist_installer/OrganisateurSetup.exe
```

---

## Structure du projet

```
organisateur-pc/
├── main.py                       entry point PyQt6
├── installer.iss                 script Inno Setup
├── requirements.txt
├── core/
│   ├── bootstrap.py              hardening Pillow (decompression bomb)
│   ├── models.py                 dataclasses Asset, DupGroup
│   ├── dedup.py                  pipeline dedup (parallèle + cancel)
│   ├── docs.py                   extraction texte PDF/DOCX/XLSX
│   ├── sort.py                   classification (regex + heuristiques + sémantique)
│   ├── clustering.py             greedy clustering CLIP
│   ├── embeddings.py             ONNX inference CLIP + e5
│   ├── exemplars.py              store des exemples par dossier
│   └── keywords.py               extraction mots-clés par fichier
├── ui/
│   ├── styles.py                 palette dark + QSS + couleurs categories
│   ├── main_window.py            fenêtre + onglets
│   ├── dedup_view.py             onglet Doublons (lignes horizontales)
│   ├── cluster_view.py           onglet Tri (clustering visuel)
│   ├── detail_panel.py           panneau d'aperçu détaillé
│   ├── result_cards.py           widgets DupGroupRow, ThumbnailCard
│   ├── learning_dialog.py        dialog Apprentissage manuel
│   └── preview.py                helpers thumbnails
├── assets/
│   └── models/
│       ├── clip/                 CLIP ViT-B/32 INT8 ONNX
│       └── e5/                   multilingual-e5-small INT8 ONNX
├── dist/Organisateur/            build PyInstaller --onedir
└── dist_installer/               OrganisateurSetup.exe (Inno Setup)
```

---

## Limitations connues

- **OCR** : nécessite Tesseract installé localement (bundlé dans l'exe, ou
  via `winget install UB-Mannheim.TesseractOCR` en dev). Sans OCR, le tri
  par texte des images est désactivé (les autres pipelines marchent).
- **PDF scannés** : si le PDF est juste une image scannée sans couche texte,
  le quasi-doublon basé sur le contenu ne peut pas le matcher. Seul le
  dedup exact (byte-à-byte) reste actif.
- **Clustering pur** : les fichiers visuellement uniques tombent dans des
  groupes d'un seul élément. C'est normal — pas de cluster forcé.
- **Confidentialité** : `sort_folders.json` stocke les **noms de tes
  dossiers** en clair. Évite de nommer un dossier avec des données
  sensibles (nom de client, données médicales, etc.) si tu partages ton PC.

---

## Notes / liens

- App Android compagnon (dedup + tri) : https://github.com/denkrfr/organisateur-tri-android
- Tesseract Windows : https://github.com/UB-Mannheim/tesseract/wiki
- Inno Setup : https://jrsoftware.org/isinfo.php

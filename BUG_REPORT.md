# Rapport d'analyse technique - Organisateur PC

Ce rapport détaille les bugs, incohérences et erreurs identifiés lors de l'analyse de l'application.

## 1. Erreurs Critiques (Assets manquants)

L'application s'appuie sur des modèles de Machine Learning locaux qui sont absents du dépôt ou mal configurés :
- **Modèle E5 absent** : Le répertoire `assets/models/e5/` est totalement manquant. Le code dans `core/embeddings.py` s'attend à y trouver `model.onnx` et `tokenizer.json`.
- **Modèle CLIP incomplet** : Le répertoire `assets/models/clip/` contient les fichiers de configuration JSON mais **les fichiers binaires ONNX (`vision_model.onnx`, `text_model.onnx`) sont absents**.
- **Impact** : Toutes les fonctionnalités de "Tri par ressemblance" et de "Recherche sémantique" sont inopérantes.

## 2. Configuration API (Modèles inexistants)

Dans `core/api_providers.py`, les modèles configurés pour le tri via Cloud sont des placeholders non valides :
- `GEMINI_MODEL = "gemini-2.5-flash"` (La version actuelle est 1.5).
- `OPENAI_MODEL = "gpt-5-nano"` (Le modèle GPT-5 n'est pas encore disponible).
- **Impact** : L'utilisation de l'IA distante échouera systématiquement avec des erreurs 404/400.

## 3. Incohérences de Documentation vs Réalité

Plusieurs affirmations du `README.md` ne correspondent pas à l'état du code ou de l'environnement :
- **Version de Python** : Le README annonce **Python 3.14**, alors que la version actuelle stable est la 3.13 et que l'environnement de développement tourne en **3.12**.
- **Bundling Tesseract** : Le README indique que Tesseract est "bundlé dans l'exe", mais le code dans `core/sort.py` (`_find_tesseract_binary`) cherche le binaire dans des chemins d'installation standards de Windows (Program Files), suggérant qu'il doit être installé séparément.
- **Statut "STUB"** : Les commentaires dans `core/sort.py` indiquent que la détection par mots-clés est un "STUB", bien qu'une implémentation basique par regex soit présente.

## 4. Problèmes de Portabilité et Robustesse

- **Dépendance exclusive à Windows** : Le module `core/api_key_store.py` utilise l'API **DPAPI** de Windows via `ctypes.windll.crypt32`. Cela rend l'application impossible à lancer sur Linux ou macOS sans modification, malgré l'utilisation de frameworks cross-platform comme PyQt6.
- **Absence de vérifications au démarrage** : `main.py` lance l'interface sans vérifier la présence des modèles ONNX ou des dépendances critiques. Les erreurs ne surviennent qu'au moment de l'utilisation des fonctions, ce qui peut mener à des crashs silencieux ou des exceptions non gérées dans les threads.

## 5. Environnement de test

- Le test de fumée (`smoke_test.py`) échoue dans l'environnement actuel car les bibliothèques système nécessaires à Qt (libxcb) sont manquantes, empêchant l'initialisation de `QApplication`.

---
*Rapport généré le 19 Mai 2024.*

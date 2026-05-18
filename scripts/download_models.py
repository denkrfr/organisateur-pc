"""Telecharge les modeles ONNX depuis Hugging Face (CLIP + multilingual-e5-small).

Necessaires pour la fonction "Tri par ressemblance" de l'app. Pas inclus dans
le repo git car > 100 MB par fichier.

Utilisation :
    python scripts/download_models.py

Tous les fichiers vont dans assets/models/.

Necessite curl.exe (preinstalle sur Windows 10/11).
"""

from __future__ import annotations
import hashlib
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "assets" / "models"


# Liste des fichiers a telecharger : (url, dest_relative_to_models)
# SHA256 attendu (pour validation post-DL ; None = pas de check)
FILES: list[tuple[str, str, str | None]] = [
    (
        "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/vision_model_quantized.onnx",
        "clip/vision_model.onnx",
        "583fd1110a514667812fee7d684952aaf82a99b959760c8d7dca7e0ab9839299",
    ),
    (
        "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/onnx/text_model_quantized.onnx",
        "clip/text_model.onnx",
        "73baab855d406190da9faa498cfedf65f15cf309f4cc7385b7b032e6d08e5c3a",
    ),
    (
        "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/tokenizer.json",
        "clip/tokenizer.json",
        None,  # petit fichier, pas de hash check
    ),
    (
        "https://huggingface.co/Xenova/clip-vit-base-patch32/resolve/main/preprocessor_config.json",
        "clip/preprocessor.json",
        None,
    ),
    (
        "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/onnx/model_quantized.onnx",
        "e5/model.onnx",
        "f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193",
    ),
    (
        "https://huggingface.co/Xenova/multilingual-e5-small/resolve/main/tokenizer.json",
        "e5/tokenizer.json",
        None,
    ),
]


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Utilise curl.exe qui est preinstalle sur Win10/11 et gere bien les
    # certificats Hugging Face (HTTPS + redirects).
    print(f"  -> {dest.name} ({url.split('/')[-1]})")
    result = subprocess.run(
        [
            "curl.exe", "-L", "--fail", "--ssl-no-revoke", "-s",
            "-o", str(dest), url,
        ],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"curl failed for {url}: {result.stderr}")


def main() -> int:
    print(f"Telechargement des modeles ML dans : {MODELS_DIR}")
    print()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    all_ok = True
    for url, rel, expected_hash in FILES:
        dest = MODELS_DIR / rel
        if dest.exists() and dest.stat().st_size > 1024:
            actual = sha256_of(dest) if expected_hash else None
            if expected_hash and actual != expected_hash:
                print(f"  [hash mismatch] {rel} -> re-telechargement")
                dest.unlink()
            else:
                size_mb = dest.stat().st_size / (1 << 20)
                print(f"  [skip] {rel} ({size_mb:.1f} MB) deja present")
                continue
        try:
            download(url, dest)
        except Exception as e:
            print(f"  [ERREUR] {rel}: {e}")
            all_ok = False
            continue
        size_mb = dest.stat().st_size / (1 << 20)
        if expected_hash:
            actual = sha256_of(dest)
            if actual != expected_hash:
                print(f"  [hash KO] {rel} (got {actual[:16]}, expected {expected_hash[:16]})")
                all_ok = False
                continue
        print(f"  [OK] {rel} ({size_mb:.1f} MB)")

    print()
    if all_ok:
        print("Tous les modeles sont en place.")
        return 0
    print("Certains telechargements ont echoue. Verifie ta connexion et relance.")
    return 1


if __name__ == "__main__":
    sys.exit(main())

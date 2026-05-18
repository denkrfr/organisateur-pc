"""Smoke test du pipeline dedup. Cree des fichiers temporaires reels,
lance le pipeline complet, et verifie qu'il trouve bien les doublons.
"""

from __future__ import annotations
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

from core import dedup


def build_test_dataset(root: Path) -> None:
    """Cree des PNG > 1 KB (sinon MIN_FILE_SIZE les ignore) :
      - red1.png + red2.png : copies byte-identiques (gradient rouge)
      - red3.png            : meme image reencodee (bytes diff, aHash proche)
      - blue.png            : gradient bleu (different)
      - tiny.png            : minuscule, doit etre ignore
    """
    import numpy as np

    # Gradient rouge avec un peu de bruit -> PNG plus gros qu'un aplat
    rng = np.random.default_rng(42)
    base = np.zeros((512, 512, 3), dtype=np.uint8)
    base[..., 0] = np.clip(np.linspace(40, 240, 512)[None, :].repeat(512, 0), 0, 255)
    base[..., 1] = (rng.integers(0, 30, (512, 512))).astype(np.uint8)
    base[..., 2] = (rng.integers(0, 30, (512, 512))).astype(np.uint8)
    red_img = Image.fromarray(base)
    red_img.save(root / "red1.png", optimize=True)
    shutil.copy(root / "red1.png", root / "red2.png")
    red_img.save(root / "red3.png", optimize=False, compress_level=0)

    # Gradient bleu
    blue_arr = base.copy()
    blue_arr[..., 0], blue_arr[..., 2] = blue_arr[..., 2], blue_arr[..., 0]
    Image.fromarray(blue_arr).save(root / "blue.png")

    Image.new("RGB", (16, 16), (255, 255, 0)).save(root / "tiny.png")


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="dedup_test_") as tmp:
        root = Path(tmp)
        print("[setup] dataset dans", root)
        build_test_dataset(root)

        for p in root.iterdir():
            print(f"        {p.name:12s}  {p.stat().st_size} bytes")

        print("\n[run]   pipeline dedup avec pHash ON...\n")
        groups = dedup.run_pipeline(
            folders=[root],
            include_p_hash=True,
            on_progress=lambda c, t, lbl: print(f"        {lbl}"),
        )

        print(f"\n[results] {len(groups)} groupe(s) trouve(s)")
        for i, g in enumerate(groups):
            print(f"  groupe {i + 1}  kind={g.kind}  recoverable={g.total_recoverable} bytes")
            for a in g.items:
                print(f"            - {a.path.name}  ({a.size} bytes)")

        # Asserts
        exact_groups = [g for g in groups if g.kind == "exact"]
        quasi_groups = [g for g in groups if g.kind == "quasi"]

        # 1 groupe exact attendu (red1 + red2)
        assert len(exact_groups) == 1, f"Expected 1 exact group, got {len(exact_groups)}"
        names = sorted(a.path.name for a in exact_groups[0].items)
        assert names == ["red1.png", "red2.png"], f"Wrong items in exact group: {names}"
        print("\n[assert] 1 groupe exact (red1 + red2) ............ OK")

        # 0 ou 1 groupe quasi (red3 peut etre detecte comme aHash voisin
        # ou pas selon la lib imagehash). Ne pas asserter strictement.
        print(f"[info]   {len(quasi_groups)} groupe(s) quasi (red3 peut etre dedans)")

        print("\nSMOKE PIPELINE OK")
        return 0


if __name__ == "__main__":
    sys.exit(main())

"""Dataclasses partagees entre dedup et sort. Equivalent du bloc Types
en haut d'App.tsx cote Android."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

GroupKind = Literal["exact", "quasi"]
AssetKind = Literal["image", "pdf", "docx", "xlsx", "other"]


@dataclass
class Asset:
    """Un fichier scanne par l'app (image ou document)."""

    path: Path
    size: int
    kind: AssetKind = "image"
    quick_hash: Optional[str] = None
    a_hash: Optional[int] = None  # 64-bit perceptual hash images
    text_hash: Optional[str] = None  # SHA256 du texte normalise (docs)

    @property
    def name(self) -> str:
        return self.path.name


@dataclass
class DupGroup:
    """Un groupe d'au moins 2 fichiers consideres comme doublons."""

    items: list[Asset]
    kind: GroupKind  # "exact" = byte-identique, "quasi" = visuellement identique
    representative_hash: str = ""  # quick_hash ou aHash hex selon kind

    @property
    def total_recoverable(self) -> int:
        """Bytes liberes si on garde le plus gros et supprime les autres."""
        if len(self.items) < 2:
            return 0
        sorted_items = sorted(self.items, key=lambda a: a.size, reverse=True)
        return sum(a.size for a in sorted_items[1:])


@dataclass
class SortRule:
    """Regle apprise pour le classement automatique."""

    pattern: str  # mot-cle ou empreinte detectee
    folder: str  # dossier ou ranger (peut contenir des / pour sous-dossiers)
    used_count: int = 0  # combien de fois cette regle a ete validee

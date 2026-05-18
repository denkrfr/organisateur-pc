## v1.1.2 — Fix doublons faux positifs + UX clarté

### Faux positifs quasi-doublons (fix important)

Avant : la détection quasi (perceptual hash) avait un seuil **5 bits sur 64** (≈ 92% similarité) qui regroupait beaucoup d'images visuellement proches **sans être des vrais doublons** (ex : 2 paysages au lever du soleil avec compositions couleur proches).

Maintenant :
- Seuils durcis : **2** pour photos (≈ 97% similarité) et **3** pour screenshots (≈ 95%). Ne capture plus que les vraies recompressions/exports HEIC→JPG.
- **Case "Détecter quasi-doublons" décochée par défaut**. Tu coches uniquement si tu veux retrouver les compressions WhatsApp / exports HEIC. Tooltip explicatif sur la case.

Si tu lances un scan normal (case décochée), tu n'as **plus que les vrais doublons byte-identiques** (zéro faux positif possible).

### "LE + GROS" → "À garder"

Le tag vert sur le fichier le plus volumineux était cryptique. Maintenant :
- Tag rebaptisé **"À garder"** (avec tooltip : "Version la plus volumineuse, généralement l'originale. Recommandé de la garder.")
- Boutons rebaptisés : "Garder la plus grosse, cocher les autres" / "Tous groupes : garder la version la plus volumineuse"

### Installation

1. Télécharge `Organisateur-v1.1.2-portable-windows.zip` (~292 Mo)
2. Clic-droit → Extraire tout
3. Double-clic sur `Organisateur.exe`

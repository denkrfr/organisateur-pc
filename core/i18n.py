"""Systeme de traduction FR/EN simple.

Architecture :
  - Dict STRINGS : key -> {"fr": "...", "en": "..."}
  - get_lang() / set_lang() : etat global
  - t(key) : retourne le texte dans la langue active
  - Persistance dans ~/.organisateur-pc/language.txt

Usage :
    from core.i18n import t
    label = QLabel(t("dedup.title"))

Quand l'user change la langue via l'UI :
    from core.i18n import set_lang
    set_lang("en")  # sauve + change l'etat
    # Puis on demande a l'user de redemarrer l'app pour appliquer (les
    # widgets deja construits ne se re-render pas automatiquement).
"""

from __future__ import annotations
from pathlib import Path
from typing import Literal

Lang = Literal["fr", "en"]

_CONFIG_FILE = Path.home() / ".organisateur-pc" / "language.txt"

_current_lang: Lang = "fr"

# ===========================================================================
# Dictionnaire de traductions
# Convention de cles : "<module>.<element>" ou "<contexte>.<bouton>"
# ===========================================================================
STRINGS: dict[str, dict[str, str]] = {

    # --- Generique / commun ---
    "common.ok":          {"fr": "OK",            "en": "OK"},
    "common.cancel":      {"fr": "Annuler",       "en": "Cancel"},
    "common.confirm":     {"fr": "Confirmer",     "en": "Confirm"},
    "common.yes":         {"fr": "Oui",           "en": "Yes"},
    "common.no":          {"fr": "Non",           "en": "No"},
    "common.close":       {"fr": "Fermer",        "en": "Close"},
    "common.back":        {"fr": "← Retour",      "en": "← Back"},
    "common.done":        {"fr": "Termine",       "en": "Done"},
    "common.error":       {"fr": "Erreur",        "en": "Error"},
    "common.warning":     {"fr": "Avertissement", "en": "Warning"},
    "common.empty":       {"fr": "Vide",          "en": "Empty"},
    "common.finished":    {"fr": "[FINI]",        "en": "[DONE]"},
    "common.loading":     {"fr": "Chargement...", "en": "Loading..."},

    # --- MainWindow / Tabs ---
    "main.window_title":  {"fr": "Organisateur — Doublons & Tri par ressemblance",
                           "en": "Organizer — Duplicates & Sort by similarity"},
    "main.tab_dedup":     {"fr": "Doublons",      "en": "Duplicates"},
    "main.tab_sort":      {"fr": "Tri",           "en": "Sort"},
    "main.lang_label":    {"fr": "Langue :",      "en": "Language:"},
    "main.lang_changed":  {"fr": "Langue changee",
                           "en": "Language changed"},
    "main.lang_restart":  {"fr": "La nouvelle langue sera appliquee au prochain demarrage de l'app. Tu peux fermer et relancer maintenant.",
                           "en": "The new language will apply on next app startup. You can close and relaunch now."},

    # --- DedupView ---
    "dedup.title":              {"fr": "Detection de doublons",
                                 "en": "Duplicate detection"},
    "dedup.subtitle":           {"fr": "Scanne les dossiers pour les doublons exacts et quasi-doublons (images, videos, PDF/Word/Excel). 100% local.",
                                 "en": "Scans folders for exact and near-duplicates (images, videos, PDF/Word/Excel). 100% local."},
    "dedup.add_folder":         {"fr": "Ajouter dossier", "en": "Add folder"},
    "dedup.remove":             {"fr": "Retirer", "en": "Remove"},
    "dedup.scan":               {"fr": "Scanner", "en": "Scan"},
    "dedup.cancel_scan":        {"fr": "Annuler", "en": "Cancel"},
    "dedup.include_phash":      {"fr": "Detecter aussi les quasi-doublons (recompressions, exports HEIC/JPG)",
                                 "en": "Also detect near-duplicates (recompressions, HEIC/JPG exports)"},
    "dedup.include_phash_tip":  {"fr": "Decoche par defaut : detection visuelle via aHash qui peut generer des faux positifs. A activer surtout pour les compressions WhatsApp / exports HEIC->JPG.",
                                 "en": "Off by default: visual detection via aHash which may produce false positives. Useful for WhatsApp compressions / HEIC->JPG exports."},
    "dedup.results":            {"fr": "Resultats du scan", "en": "Scan results"},
    "dedup.groups_badge":       {"fr": "{n} groupes", "en": "{n} groups"},
    "dedup.filter":             {"fr": "Afficher :", "en": "Filter:"},
    "dedup.filter_all":         {"fr": "Tous les groupes", "en": "All groups"},
    "dedup.filter_exact":       {"fr": "Exacts uniquement", "en": "Exact only"},
    "dedup.filter_quasi":       {"fr": "Quasi uniquement", "en": "Near only"},
    "dedup.empty":              {"fr": "Lance un scan pour voir les doublons.",
                                 "en": "Start a scan to see duplicates."},
    "dedup.no_dup_found":       {"fr": "Aucun doublon trouve.",
                                 "en": "No duplicate found."},
    "dedup.bulk_keep_biggest":  {"fr": "Tous groupes : garder la version la plus volumineuse",
                                 "en": "All groups: keep the largest version"},
    "dedup.bulk_uncheck":       {"fr": "Tout decocher", "en": "Uncheck all"},
    "dedup.trash_btn":          {"fr": "Envoyer a la corbeille systeme",
                                 "en": "Send to system trash"},
    "dedup.footer_zero":        {"fr": "0 groupe trouve", "en": "0 group found"},
    "dedup.footer_groups":      {"fr": "{n} groupe(s) trouves — {size} recuperables au total",
                                 "en": "{n} group(s) found — {size} recoverable total"},
    "dedup.footer_checked":     {"fr": "{n} fichier(s) coche(s) — {size} a liberer",
                                 "en": "{n} file(s) checked — {size} to free"},
    "dedup.trash_confirm_title":{"fr": "Envoyer a la corbeille ?",
                                 "en": "Send to trash?"},
    "dedup.trash_confirm_body": {"fr": "{n} fichier(s) seront envoyes a la corbeille systeme.\n\n{size} seront liberes.\n\nTu pourras les recuperer depuis la corbeille Windows tant qu'elle n'est pas vide.",
                                 "en": "{n} file(s) will be sent to the system trash.\n\n{size} will be freed.\n\nYou can restore them from the Windows trash as long as it isn't emptied."},
    "dedup.nothing_to_delete":  {"fr": "Coche au moins un fichier.",
                                 "en": "Check at least one file."},
    "dedup.trash_done":         {"fr": "{n} fichier(s) envoyes a la corbeille.",
                                 "en": "{n} file(s) sent to trash."},
    "dedup.trash_progress":     {"fr": "Envoi a la corbeille : {done} / {total}",
                                 "en": "Sending to trash: {done} / {total}"},
    "dedup.back_tip":           {"fr": "Effacer les resultats et revenir a la selection de dossiers",
                                 "en": "Clear results and return to folder selection"},
    "dedup.pick_folder":        {"fr": "Choisir un dossier a scanner",
                                 "en": "Choose a folder to scan"},
    "dedup.no_folder_title":    {"fr": "Pas de dossier", "en": "No folder"},
    "dedup.no_folder_body":     {"fr": "Ajoute au moins un dossier a scanner.",
                                 "en": "Add at least one folder to scan."},
    "dedup.init":               {"fr": "Initialisation...", "en": "Initializing..."},
    "dedup.cancelling":         {"fr": "Annulation en cours...", "en": "Cancelling..."},
    "dedup.cancelled":          {"fr": "Scan annule.", "en": "Scan cancelled."},
    "dedup.scan_done":          {"fr": "Termine. {n} groupe(s) trouve(s).",
                                 "en": "Done. {n} group(s) found."},
    "dedup.scan_error_title":   {"fr": "Erreur de scan", "en": "Scan error"},
    "dedup.show_more":          {"fr": "Afficher {n} de plus ({rest} restants)",
                                 "en": "Show {n} more ({rest} remaining)"},
    "dedup.trash_warning_title":{"fr": "Suppression OK mais probleme UI",
                                 "en": "Deletion OK but UI issue"},
    "dedup.trash_progress_file":{"fr": "Envoi a la corbeille : {done} / {total} — {file}",
                                 "en": "Sending to trash: {done} / {total} — {file}"},
    "dedup.trash_done_full":    {"fr": "[FINI] {n} fichier(s) envoyes a la corbeille.",
                                 "en": "[DONE] {n} file(s) sent to trash."},
    "dedup.trash_errors":       {"fr": "\n\n{n} erreur(s) :\n",
                                 "en": "\n\n{n} error(s):\n"},

    # --- ClusterView ---
    "sort.title":               {"fr": "Tri par ressemblance", "en": "Sort by similarity"},
    "sort.subtitle":            {"fr": "Regroupe automatiquement les fichiers qui se ressemblent. Pour chaque groupe, tape un nom de dossier et clique Deplacer. Pas d'apprentissage prealable necessaire.",
                                 "en": "Automatically groups similar files. For each group, type a folder name and click Move. No prior training needed."},
    "sort.sources_label":       {"fr": "Fichiers et dossiers a trier :",
                                 "en": "Files and folders to sort:"},
    "sort.add_files":           {"fr": "+ Ajouter fichiers...", "en": "+ Add files..."},
    "sort.add_dir":             {"fr": "+ Ajouter dossier...", "en": "+ Add folder..."},
    "sort.remove":              {"fr": "Retirer", "en": "Remove"},
    "sort.clear":               {"fr": "Vider la liste", "en": "Clear list"},
    "sort.clear_tip":           {"fr": "Retire tous les fichiers/dossiers de la liste (ne touche pas aux fichiers sur disque)",
                                 "en": "Removes all files/folders from the list (does not touch files on disk)"},
    "sort.dest_root":           {"fr": "Racine de classement :",
                                 "en": "Destination root:"},
    "sort.dest_placeholder":    {"fr": "(par defaut = meme dossier que source)",
                                 "en": "(default = same folder as source)"},
    "sort.dest_change":         {"fr": "Changer...", "en": "Change..."},
    "sort.recursive":           {"fr": "Inclure sous-dossiers", "en": "Include subfolders"},
    "sort.filters":             {"fr": "Ignorer icones et fichiers systeme",
                                 "en": "Ignore icons and system files"},
    "sort.threshold":           {"fr": "Stricte du regroupement :",
                                 "en": "Grouping strictness:"},
    "sort.threshold_help":      {"fr": "Plus haut = groupes plus precis mais petits (et plus de singletons). Plus bas = groupes plus larges, regroupe les legeres variations visuelles. Defaut 0.78 = bon compromis pour des photos.",
                                 "en": "Higher = stricter, smaller and more precise groups (and more singletons). Lower = looser, groups visual variations together. Default 0.78 = good compromise for photos."},
    "sort.analyze":             {"fr": "Analyser et regrouper",
                                 "en": "Analyze and group"},
    "sort.empty":               {"fr": "Choisis un dossier en vrac et clique \"Analyser et regrouper\".",
                                 "en": "Pick an unsorted folder and click \"Analyze and group\"."},
    "sort.footer_zero":         {"fr": "0 groupe", "en": "0 group"},
    "sort.footer_remaining":    {"fr": "{n} groupe(s) restant(s)",
                                 "en": "{n} group(s) remaining"},
    "sort.footer_with_iso":     {"fr": "{n} groupe(s) restant(s) — dont {iso} isole(s)",
                                 "en": "{n} group(s) remaining — including {iso} isolated"},
    "sort.all_done":            {"fr": "Tous les groupes traites.",
                                 "en": "All groups processed."},
    "sort.move_all":            {"fr": "Deplacer TOUS les groupes nommes",
                                 "en": "Move ALL named groups"},
    "sort.move_all_tip":        {"fr": "Deplace en sequence chaque groupe pour lequel tu as tape un nom de dossier. Les groupes sans nom sont ignores.",
                                 "en": "Sequentially moves each group with a folder name typed. Groups without a name are skipped."},
    "sort.move_singletons":     {"fr": "Deplacer les {n} isoles dans un album commun",
                                 "en": "Move the {n} isolated files to a common album"},
    "sort.move_singletons_tip": {"fr": "Regroupe tous les fichiers qui n'ont aucun similaire dans un meme dossier 'Autres' (nom modifiable).",
                                 "en": "Groups all files with no similar one in a single 'Others' folder (name editable)."},
    "sort.back_tip":             {"fr": "Effacer les groupes et revenir a la selection de fichiers",
                                  "en": "Clear groups and return to file selection"},
    "sort.analyzing":            {"fr": "Analyse...", "en": "Analyzing..."},
    "sort.cluster_done":         {"fr": "[FINI] {n} groupe(s) formes — choisis un nom et clique Deplacer pour chaque.",
                                  "en": "[DONE] {n} group(s) formed — pick a name and click Move for each."},
    "sort.cluster_done_title":   {"fr": "Analyse terminee", "en": "Analysis finished"},
    "sort.cluster_done_body":    {"fr": "[FINI]\n\n{n} groupe(s) formes.\n\nPour chaque groupe : tape un nom de dossier et clique Deplacer. Quand t'as fini, clique Retour pour effacer et relancer une analyse.",
                                  "en": "[DONE]\n\n{n} group(s) formed.\n\nFor each group: type a folder name and click Move. When done, click Back to clear and run another analysis."},
    "sort.cluster_none":         {"fr": "Aucun groupe forme.", "en": "No group formed."},
    "sort.cluster_none_popup":   {"fr": "[FINI]\n\nAucun groupe n'a ete forme.",
                                  "en": "[DONE]\n\nNo group was formed."},

    # --- ClusterCard ---
    "card.move_btn":             {"fr": "Deplacer ce groupe", "en": "Move this group"},
    "card.move_btn_tip":         {"fr": "Cree le dossier (si necessaire) et y deplace tous les fichiers du groupe",
                                  "en": "Creates the folder (if needed) and moves all files in the group there"},
    "card.skip":                 {"fr": "Ignorer", "en": "Skip"},
    "card.folder_label":         {"fr": "Nom du dossier :", "en": "Folder name:"},
    "card.folder_placeholder":   {"fr": "Tape un nom (ex: skyvision, Plage, Factures...)",
                                  "en": "Type a name (e.g., skyvision, Beach, Invoices...)"},
    "card.see_files":            {"fr": "Voir / decocher les intrus ({n} fichiers)",
                                  "en": "View / uncheck intruders ({n} files)"},
    "card.see_files_tip":        {"fr": "Optionnel : voir tous les fichiers et decocher ceux qui n'ont rien a faire la",
                                  "en": "Optional: view all files and uncheck those that don't belong"},
    "card.elargir":              {"fr": "Elargir le regroupement", "en": "Loosen grouping"},
    "card.elargir_tip":          {"fr": "Re-lance le clustering avec un seuil de similarite reduit de 0.05. Les groupes deviendront plus larges. Utile si ce groupe te semble trop fin.",
                                  "en": "Reruns clustering with a similarity threshold reduced by 0.05. Groups will become broader. Useful if this group seems too narrow."},
    "card.name_required":        {"fr": "Tape un nom de dossier avant de deplacer.",
                                  "en": "Type a folder name before moving."},

    # --- DupGroupRow / ResultCards ---
    "group.keep":                {"fr": "A garder", "en": "To keep"},
    "group.keep_tip":            {"fr": "Version la plus volumineuse, generalement l'originale. Recommande de la garder.",
                                  "en": "Largest version, usually the original. Recommended to keep."},
    "group.see_modify":          {"fr": "Voir / Modifier la selection",
                                  "en": "View / Edit selection"},
    "group.collapsed_hint":      {"fr": "...et {n} de plus", "en": "...and {n} more"},

    # --- DupGroupContentsDialog ---
    "dlg.dup.title":             {"fr": "Groupe de {n} fichiers ({kind})",
                                  "en": "Group of {n} files ({kind})"},
    "dlg.dup.header":            {"fr": "{n} fichiers - {size} recuperables si tu coches tous sauf le + gros",
                                  "en": "{n} files - {size} recoverable if you check all except the largest"},
    "dlg.dup.info":              {"fr": "✓ Coche un fichier = il sera ENVOYE A LA CORBEILLE. Decoche pour le garder. Le + gros (en haut) est generalement la meilleure copie.",
                                  "en": "✓ Check a file = it will be SENT TO TRASH. Uncheck to keep. The largest (at top) is usually the best copy."},
    "dlg.dup.check_all_but_first":{"fr": "Cocher tout sauf le + gros",
                                  "en": "Check all except the largest"},
    "dlg.dup.uncheck_all":       {"fr": "Tout decocher", "en": "Uncheck all"},
    "dlg.dup.check_all":         {"fr": "Tout cocher", "en": "Check all"},
    "dlg.dup.count":             {"fr": "{n} / {total} a supprimer ({size})",
                                  "en": "{n} / {total} to delete ({size})"},
    "dlg.dup.validate":          {"fr": "Valider la selection", "en": "Confirm selection"},
    "dlg.dup.best_copy":         {"fr": "Meilleure copie (plus volumineuse)",
                                  "en": "Best copy (largest)"},
    "dlg.dup.click_open_tip":    {"fr": "Clique pour ouvrir le fichier",
                                  "en": "Click to open the file"},

    # --- ClusterContentsDialog ---
    "dlg.cluster.title":         {"fr": "Contenu du groupe ({n} fichiers)",
                                  "en": "Group contents ({n} files)"},
    "dlg.cluster.info":          {"fr": "Decoche les fichiers qui ne devraient pas etre dans ce groupe. Seuls les fichiers coches seront deplaces.",
                                  "en": "Uncheck files that shouldn't be in this group. Only checked files will be moved."},
    "dlg.cluster.checked":       {"fr": "{n} / {total} coches",
                                  "en": "{n} / {total} checked"},

    # --- TriModeDialog ---
    "trimode.window_title":      {"fr": "Mode de tri", "en": "Sort mode"},
    "trimode.title":             {"fr": "Comment veux-tu trier tes photos ?",
                                  "en": "How do you want to sort your photos?"},
    "trimode.local":             {"fr": "Mode local (CLIP)", "en": "Local mode (CLIP)"},
    "trimode.local_tag":         {"fr": "100% PRIVE", "en": "100% PRIVATE"},
    "trimode.local_desc":        {"fr": "Aucune photo ne quitte ton PC. Modele IA local (CLIP, ~150 Mo deja embarque dans l'app). Tourne sur le CPU.\n\nRegroupe par ressemblance visuelle (memes couleurs, formes, scenes). Plus lent (~0.5 sec par photo), plus restrictif sur les criteres.",
                                  "en": "No photo leaves your PC. Local AI model (CLIP, ~150 MB embedded in the app). Runs on CPU.\n\nGroups by visual similarity (same colors, shapes, scenes). Slower (~0.5s per photo), stricter on criteria."},
    "trimode.local_btn":         {"fr": "Utiliser le mode local",
                                  "en": "Use local mode"},
    "trimode.api":               {"fr": "Mode IA cloud", "en": "Cloud AI mode"},
    "trimode.api_tag":           {"fr": "RAPIDE & MALIN", "en": "FAST & SMART"},
    "trimode.api_desc":          {"fr": "Tes photos sont envoyees a Google Gemini ou OpenAI GPT-5 nano pour analyse. Plus rapide et plus precis, regroupe par THEME (plage, repas, captures de cours, animaux, documents...) et te propose un nom d'album pour chaque groupe.\n\nNecessite une cle API (gratuite pour Gemini).",
                                  "en": "Your photos are sent to Google Gemini or OpenAI GPT-5 nano for analysis. Faster and more accurate, groups by THEME (beach, meals, course screenshots, animals, documents...) and suggests an album name for each group.\n\nRequires an API key (free for Gemini)."},
    "trimode.api_btn":           {"fr": "Utiliser le mode IA cloud",
                                  "en": "Use cloud AI mode"},
    "trimode.api_configured":    {"fr": "✓ Configure : {provider}",
                                  "en": "✓ Configured: {provider}"},
    "trimode.api_reset":         {"fr": "Reset cle API", "en": "Reset API key"},

    # --- ApiSetupDialog (le plus gros) ---
    "api.window_title":          {"fr": "Configuration du mode IA cloud",
                                  "en": "Cloud AI mode setup"},
    "api.step1_title":           {"fr": "Mode IA cloud", "en": "Cloud AI mode"},
    "api.step1_body":            {"fr": "Cette option utilise un service d'IA en ligne (Google Gemini ou OpenAI GPT-5 nano) pour trier tes photos par theme. Le tri est plus rapide et plus precis qu'avec le mode local, et l'IA propose elle-meme des noms d'albums.",
                                  "en": "This option uses an online AI service (Google Gemini or OpenAI GPT-5 nano) to sort your photos by theme. Sorting is faster and more accurate than local mode, and the AI suggests album names."},
    "api.step1_warn_title":      {"fr": "⚠ Important sur la confidentialite",
                                  "en": "⚠ Important about privacy"},
    "api.step1_accept":          {"fr": "J'accepte, continuer",
                                  "en": "I accept, continue"},
    "api.step2_title":           {"fr": "Choisis ton fournisseur",
                                  "en": "Choose your provider"},
    "api.step2_next":            {"fr": "Suite", "en": "Next"},
    "api.step3_save":            {"fr": "Enregistrer et terminer",
                                  "en": "Save and finish"},
}


# ===========================================================================
# API publique
# ===========================================================================
def get_lang() -> Lang:
    return _current_lang


def set_lang(lang: Lang) -> None:
    """Change la langue active + persiste sur disque. Les widgets deja
    construits ne se rafraichissent pas : un redemarrage est necessaire.
    """
    global _current_lang
    if lang not in ("fr", "en"):
        return
    _current_lang = lang
    try:
        _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CONFIG_FILE.write_text(lang, encoding="utf8")
    except Exception:  # noqa: BLE001
        pass


def load_lang() -> Lang:
    """Charge la langue depuis le fichier de config au demarrage."""
    global _current_lang
    try:
        if _CONFIG_FILE.exists():
            content = _CONFIG_FILE.read_text(encoding="utf8").strip()
            if content in ("fr", "en"):
                _current_lang = content  # type: ignore[assignment]
                return _current_lang
    except Exception:  # noqa: BLE001
        pass
    return _current_lang


def t(key: str, **kwargs: object) -> str:
    """Retourne le texte traduit pour la cle. Si la cle existe pas, on
    retourne la cle elle-meme (utile pour reperer les strings manquantes).

    Supporte des substitutions style {n}, {size}, etc. via str.format(**kwargs).
    """
    entry = STRINGS.get(key)
    if entry is None:
        return key  # fallback : on voit la cle = c'est qu'on a oublie de traduire
    text = entry.get(_current_lang) or entry.get("fr") or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, IndexError):
            return text
    return text


# Charge la langue automatiquement a l'import
load_lang()

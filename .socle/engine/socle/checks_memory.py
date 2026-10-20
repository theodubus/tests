"""Contrôles de la mémoire et des demandes humaines.

Chaque fonction est un contrôle déterministe : elle ajoute des constats au
rapport, et un constat de gravité « erreur » fait échouer le passage.
"""

from __future__ import annotations

import re
import subprocess
import time
from functools import lru_cache
from urllib.parse import unquote

from socle import config, requests as demandes, language as langue, links as liens, memory as memoire, utils as outils
from socle.messages import trad
from socle.context import controle

TYPE_DE_COUCHE = {v: k for k, v in memoire.TYPES.items()}
TRANSITIONS_ADR = {
    ("proposee", "acceptee"), ("proposee", "rejetee"), ("proposee", "abandonnee"),
    ("acceptee", "remplacee"), ("acceptee", "abandonnee"),
}


est_prive = memoire.est_prive


# --------------------------------------------------------------------------
# Format
# --------------------------------------------------------------------------


@controle("memoire.format")
def format_memoire(ctx, r):
    """En-têtes, couches, identifiants, statuts : la mémoire se lit par script."""
    ch = ctx.projet.chemins
    # Au format 3, le backlog est un dossier, qu'aucun sujet ne rend requis.
    for requis in (ch.canonique, ch.actif) + (() if ch.backlog_en_dossier else (ch.backlog,)):
        if requis not in ctx.fichiers:
            r.erreur("memoire.format", trad("fichier de mémoire requis absent"), requis)
    for chemin, f in sorted(ctx.memoire.fichiers.items()):
        attendue = memoire.couche_attendue(chemin)
        if attendue == "inconnue":
            r.erreur("memoire.format", trad("fichier hors des couches connues de la mémoire"), chemin)
            continue
        if f.couche is None:
            r.erreur("memoire.format", trad("en-tête `<!-- socle: couche=… zone=… -->` absent"), chemin, 1)
            continue
        if f.couche != attendue:
            r.erreur("memoire.format", trad("couche déclarée « {couche} », l'emplacement impose « {attendue} »",
                                            couche=f.couche, attendue=attendue), chemin, 1)
        zone_lieu = "privee" if est_prive(chemin) else "publique"
        if f.zone not in memoire.ZONES:
            r.erreur("memoire.format", trad("zone non déclarée (`zone=publique` ou `zone=privee`)"), chemin, 1)
        elif f.zone != zone_lieu:
            r.erreur("memoire.format", trad("zone déclarée « {zone} » dans un emplacement « {zone_lieu} »",
                                            zone=f.zone, zone_lieu=zone_lieu), chemin, 1)
        _format_entrees(r, chemin, f, attendue, zone_lieu == "privee")
        # Un titre mal formé fait disparaître l'entrée de toute lecture
        # (relevé de la passe de recul, D).
        for ligne, titre in f.illisibles:
            r.erreur("memoire.format", trad("titre d'entrée illisible : « {titre} » — l'entrée n'est pas lue ; "
                                            "forme attendue : `## J-AAAA-MM-JJ-X — titre`", titre=titre[:60]), chemin, ligne)

    for ident, defs in ctx.memoire.definitions().items():
        if len(defs) > 1:
            lieux = ", ".join(f"{d.fichier}:{d.ligne}" for d in defs)
            r.erreur("memoire.format", trad("`{ident}` est défini {n} fois ({lieux})",
                                            ident=ident, n=len(defs), lieux=lieux), defs[0].fichier, defs[0].ligne)


def _format_entrees(r, chemin, f, couche, prive):
    nom = chemin.rsplit("/", 1)[-1]
    if couche == "actif":
        for e in f.entrees:
            r.erreur("memoire.format", trad("`{id}` défini dans le chantier actif, qui est réécrit : un "
                                            "identifiant stable vit dans une couche durable", id=e.id), chemin, e.ligne)
        return
    attendu = TYPE_DE_COUCHE[couche]
    # `AAAA-MM.md`, puis `AAAA-MM-2.md`… quand le mois dépasse son budget (ADR-0022).
    if couche == "journal" and not re.match(r"^\d{4}-\d{2}(?:-[2-9]|-[1-9]\d+)?\.md$", nom):
        r.erreur("memoire.format", trad("un fichier de journal se nomme `AAAA-MM.md`, ou `AAAA-MM-N.md` quand "
                                        "le mois continue (N à partir de 2)"), chemin)
    premiers = [e for e in f.entrees if e.parent is None]
    if couche in ("decisions", "demandes"):
        if len(premiers) != 1:
            r.erreur("memoire.format", trad("un fichier de {couche} porte exactement une entrée ({n} "
                                            "trouvée(s))", couche=couche, n=len(premiers)), chemin)
        elif not nom.startswith(premiers[0].id):
            r.erreur("memoire.format", trad("le nom du fichier doit commencer par {id}", id=premiers[0].id), chemin)
    for e in f.entrees:
        if e.prive != prive:
            r.erreur("memoire.format", trad("`{id}` : un identifiant privé commence par P", id=e.id) if prive
                     else trad("`{id}` : un identifiant public ne commence pas par P", id=e.id), chemin, e.ligne)
        if e.parent is not None:
            if couche != "journal" or e.type not in ("F", "B"):
                r.erreur("memoire.format", trad("`{id}` imbriqué hors d'une archive de journal", id=e.id), chemin, e.ligne)
            continue
        if e.type != attendu:
            r.erreur("memoire.format", trad("`{id}` n'a pas sa place dans la couche « {couche} »",
                                            id=e.id, couche=couche), chemin, e.ligne)
            continue
        if couche == "journal":
            date = e.id.lstrip("P")[2:12]
            if not nom.startswith(date[:7]):
                r.erreur("memoire.format", trad("`{id}` est daté hors du mois de son fichier", id=e.id), chemin, e.ligne)
        if e.basculee:
            # Ni titre ni texte propres : ce sont eux qui sont privés (B-0029).
            if prive:
                r.erreur("memoire.format", trad("`{id}` : seule une entrée publique se bascule", id=e.id), chemin, e.ligne)
            if e.titre not in langue.textes("titre-basculee") or \
                    _norm(e.corps) not in {"", *(_norm(x) for x in langue.textes("texte-basculee"))}:
                r.erreur("memoire.format", trad("`{id}` basculée garde un titre ou un texte : seuls « "
                                                "{titre} » et « {texte} » restent en public",
                                                id=e.id, titre=memoire.TITRE_BASCULEE, texte=memoire.TEXTE_BASCULEE), chemin, e.ligne)
            continue
        statuts = memoire.STATUTS.get(e.type)
        if statuts is not None:
            if not e.statut:
                r.erreur("memoire.format", trad("`{id}` sans `statut` (attendu : {liste})",
                                                id=e.id, liste=', '.join(sorted(statuts))), chemin, e.ligne)
            elif e.statut not in statuts:
                r.erreur("memoire.format", trad("`{id}` : statut « {statut} » inconnu (attendu : {liste})",
                                                id=e.id, statut=e.statut, liste=', '.join(sorted(statuts))), chemin, e.ligne)
        if e.barre and e.type == "F" and e.statut != "refute":
            r.erreur("memoire.format", trad("`{id}` est barré sans être « réfuté »", id=e.id), chemin, e.ligne)


# --------------------------------------------------------------------------
# Références
# --------------------------------------------------------------------------

LIEN_RE = re.compile(r"!?\[[^\]\n]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
CODE_EN_LIGNE = re.compile(r"`([^`\n]+)`")
INTERDITS_CHEMIN = set("*?[]{}<>$|~\"' =,;()")


def ancres(texte: str) -> set[str]:
    res, vus = set(), {}
    for _, ligne, code in memoire.lignes_hors_code(texte):
        if code:
            continue
        m = memoire.TITRE_RE.match(ligne)
        if m:
            s = liens.ancre(m["reste"])
            n = vus.get(s, 0)
            res.add(s if n == 0 else f"{s}-{n}")
            vus[s] = n + 1
    return res


def _existe(ctx, chemin: str, historique: bool = False) -> bool:
    """Le chemin existe, sous son nom ou sous celui que la migration du
    format lui a donné : le journal et les demandes gelées gardent les
    anciens chemins, qui restent valides (B-0032). Avec `historique` (une
    couche qui ne se réécrit pas), un chemin qui a existé dans l'historique
    du dépôt vaut aussi : la mémoire ne suit pas un renommage (ADR-0027)."""
    chemin = chemin.strip("/")
    if _existe_tel_quel(ctx, chemin) or historique and _a_existe(ctx, chemin):
        return True
    alias = config.sous_le_format(chemin, ctx.projet.chemins.format)
    if alias != chemin and _existe_tel_quel(ctx, alias):
        return True
    return _basculee(ctx, alias) is not None or _backlog_unique(ctx, alias) or _dans_une_rustine(ctx, chemin)


RUSTINE = re.compile(r"^\+\+\+ b/(\S+)", re.M)


def _dans_une_rustine(ctx, chemin: str) -> bool:
    """Le chemin est un fichier qu'une rustine suivie du dépôt (`*.patch`,
    `*.diff`) écrit, ou l'un de ses dossiers : il existe une fois la rustine
    appliquée (B-0008, 25 cas sur le projet d'échecs)."""
    ecrits = ctx._cache.get("rustines")
    if ecrits is None:
        ecrits = set()
        for f in outils.filtrer(ctx.fichiers, ["**/*.patch", "**/*.diff"]):
            for m in RUSTINE.finditer(ctx.lire(f) or ""):
                parts = m.group(1).split("/")
                ecrits |= {"/".join(parts[:i]) for i in range(1, len(parts) + 1)}
        ctx._cache["rustines"] = ecrits
    return chemin in ecrits


# Les couches qui ne se réécrivent pas : ce qu'elles citent a existé quand
# elles l'ont écrit.
COUCHES_GELEES = ("journal", "decisions", "demandes", "canonique")


def _a_existe(ctx, chemin: str) -> bool:
    """Le chemin, ou un dossier, a existé dans l'historique du dépôt, toutes
    branches comprises. Un seul `git log` par contexte, au premier besoin."""
    connus = ctx._cache.get("historique")
    if connus is None:
        sortie = outils.git(ctx.racine, "log", "--all", "--no-renames", "--format=", "--name-only", check=False)
        connus = set()
        for f in sortie.splitlines():
            if f:
                parts = f.split("/")
                connus.update("/".join(parts[:i]) for i in range(1, len(parts) + 1))
        ctx._cache["historique"] = connus
    return chemin in connus


def _backlog_unique(ctx, chemin: str) -> bool:
    """Le backlog en un fichier, cité avant que le format 3 n'en fasse un
    dossier : le journal et les demandes gelées le citent encore (ADR-0025)."""
    return ctx.projet.chemins.backlog_en_dossier and chemin in (config.FORMAT_2.backlog,
                                                                 config.FORMAT_2.dans_prive(config.FORMAT_2.backlog))


def _basculee(ctx, chemin: str) -> str | None:
    """Le fichier qui remplace celui d'une décision basculée dans la mémoire
    privée (`ADR-0003-basculee.md` pour `ADR-0003-un-titre.md`, B-0029), ou
    d'un sujet du backlog au format 3 (ADR-0025)."""
    dossier, _, nom = chemin.rpartition("/")
    m = re.match(r"^((?:ADR|B)-\d{4})-.+\.md$", nom)
    if not m or not memoire.est_memoire(chemin):
        return None
    remplacant = f"{dossier}/{m[1]}-{BASCULEE}.md"
    return remplacant if remplacant != chemin and _existe_tel_quel(ctx, remplacant) else None


BASCULEE = "basculee"


def _alias(ctx, chemin: str) -> str:
    """Le chemin tel qu'il existe : le sien, son nom au format du projet, ou
    celui du fichier qui remplace une décision basculée."""
    if _existe_tel_quel(ctx, chemin.strip("/")):
        return chemin
    alias = config.sous_le_format(chemin, ctx.projet.chemins.format)
    return alias if _existe_tel_quel(ctx, alias) else (_basculee(ctx, alias) or alias)


def _existe_tel_quel(ctx, chemin: str) -> bool:
    if chemin in ctx._cache.setdefault("ensemble", set(ctx.fichiers)) or chemin == "":
        return True
    dossiers = ctx._cache.get("dossiers")
    if dossiers is None:
        dossiers = set()
        for f in ctx.fichiers:
            parts = f.split("/")
            for i in range(1, len(parts)):
                dossiers.add("/".join(parts[:i]))
        ctx._cache["dossiers"] = dossiers
    return chemin in dossiers


@lru_cache(maxsize=4096)
def _ignore(racine, chemin: str) -> bool:
    r = subprocess.run(["git", "check-ignore", "-q", "--no-index", chemin], cwd=racine, capture_output=True)
    return r.returncode == 0


def _racines(ctx) -> set[str]:
    if "racines" not in ctx._cache:
        ctx._cache["racines"] = {f.split("/", 1)[0] for f in ctx.fichiers}
    return ctx._cache["racines"]


def _normaliser_chemin(base_dir: str, cible: str) -> str:
    parts = [] if cible.startswith("/") else [p for p in base_dir.split("/") if p]
    for p in cible.split("/"):
        if p in ("", "."):
            continue
        if p == "..":
            if parts:
                parts.pop()
            continue
        parts.append(p)
    return "/".join(parts)


def textes_scannes(ctx) -> dict[str, str]:
    motifs = ctx.projet.gf("references", "scan", defaut=["**/*.md"])
    res = ctx.textes(motifs, ctx.projet.exclusions_docs())
    for chemin, f in ctx.memoire.fichiers.items():
        res.setdefault(chemin, f.texte)
    return res


@controle("memoire.references")
def references(ctx, r):
    """Tout identifiant, commit, fichier, lien ou chemin cité existe."""
    defs = ctx.memoire.definitions()
    prive_dispo = any(est_prive(c) for c in ctx.memoire.fichiers)
    autres: dict[str, list[tuple[str, int, str]]] = {}
    textes = textes_scannes(ctx)
    connus = depots_connus(ctx, textes.values())
    for chemin, texte in sorted(textes.items()):
        dossier = chemin.rsplit("/", 1)[0] if "/" in chemin else ""
        gele = memoire.couche_attendue(chemin) in COUCHES_GELEES
        for ident, ligne in memoire.mentions(texte):
            if ident.startswith("P"):
                if not est_prive(chemin) or not prive_dispo:
                    continue  # fuite : `memoire.prive` ; indisponible : signalé à part
            if ident not in defs:
                r.erreur("memoire.references", trad("`{ident}` ne désigne aucune entrée de la mémoire",
                                                    ident=ident), chemin, ligne)
        for i, ligne, code in memoire.lignes_hors_code(texte):
            if code:
                continue
            for type_, cible in memoire.references(ligne):
                if type_ == "id":
                    continue
                faute = verifier_ref(ctx, type_, cible, gele)
                if faute:
                    r.erreur("memoire.references", faute, chemin, i)
            for m in LIEN_RE.finditer(ligne):
                faute = _verifier_lien(ctx, chemin, dossier, m.group(1), gele)
                if faute:
                    r.erreur("memoire.references", faute, chemin, i)
            sans_refs = memoire.REF_RE.sub(" ", ligne)
            for m in CODE_EN_LIGNE.finditer(sans_refs):
                faute = _verifier_chemin_cite(ctx, m.group(1), gele)
                if faute:
                    r.erreur("memoire.references", faute, chemin, i)
                depot = depot_non_declare(ctx, m.group(1), connus)
                if depot:
                    autres.setdefault(depot, []).append((chemin, i, m.group(1)))
    # Un avertissement par dépôt, au premier endroit qui le cite.
    for depot, ou in sorted(autres.items()):
        chemin, i, jeton = ou[0]
        r.avertir("memoire.references", trad("`{jeton}` : dépôt « {depot} » non déclaré, {n} chemin(s) cité(s) "
                                             "que rien ne vérifie, et aucune adresse du projet ne le lie : un "
                                             "lien vers ce dépôt le fait connaître ; sinon ce n'est pas un "
                                             "dépôt, et la forme `x:chemin` ne lui convient pas",
                                             jeton=jeton, depot=depot, n=len(ou)), chemin, i)


def verifier_ref(ctx, type_: str, cible: str, historique: bool = False) -> str | None:
    if re.search(r"[<>…]", cible):
        return None  # un gabarit (`commit:<sha>`), pas une référence
    if type_ == "commit":
        if not re.fullmatch(r"[0-9a-f]{7,40}", cible):
            return trad("`commit:{cible}` n'est pas un SHA", cible=cible)
        if not outils.objet_existe(ctx.racine, cible):
            return trad("`commit:{cible}` n'existe pas dans ce dépôt (historique complet ? `fetch-depth: 0`)",
                        cible=cible)
    elif type_ == "fichier":
        chemin = re.split(r"[#]|:(?=\d)", cible, maxsplit=1)[0]
        if not _existe(ctx, chemin, historique) and not _ignore(ctx.racine, chemin):
            return trad("`fichier:{cible}` : {chemin} n'existe pas", cible=cible, chemin=chemin)
    elif type_ == "cmd":
        premier = cible.split()[0] if cible.split() else ""
        if "/" in premier and not _existe(ctx, premier.removeprefix("./"), historique):
            return trad("`cmd:{cible}` : {premier} n'existe pas", cible=cible, premier=premier)
    return None


def _verifier_lien(ctx, chemin_doc: str, dossier: str, cible: str, historique: bool = False) -> str | None:
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", cible) or cible.startswith("//"):
        return None  # URL : jamais suivie, aucun service externe
    # Un lien s'écrit encodé (`%20` pour une espace, `%C3%A9` pour un « é ») :
    # il désigne le chemin et l'ancre décodés (B-0020).
    chemin, _, ancre = (unquote(x) for x in cible.partition("#"))
    if chemin:
        cible_n = _normaliser_chemin(dossier, chemin)
        if not _existe(ctx, cible_n, historique) and not _ignore(ctx.racine, cible_n):
            return trad("lien mort : {cible}", cible=cible)
    else:
        cible_n = chemin_doc
    if ancre and cible_n.endswith(".md"):
        lieu = _alias(ctx, cible_n)
        if _backlog_unique(ctx, lieu):
            # L'ancre d'un sujet du fichier unique vaut tant que le sujet
            # existe, dans son fichier ou archivé au journal.
            if not any(ancre.startswith(liens.ancre(e.id) + "--") for e in ctx.memoire.entrees("B")):
                return trad("ancre morte : {cible}", cible=cible)
            return None
        texte = ctx.lire(lieu)
        if texte is not None and ancre not in ancres(texte) and ancre_au_format_2(ancre) not in ancres(texte) \
                and not _ancre_deplacee(ctx, lieu, ancre):
            return trad("ancre morte : {cible}", cible=cible)
    return None


def _ancre_deplacee(ctx, chemin: str, ancre: str) -> bool:
    """L'ancre d'une entrée qui a quitté ce fichier, écrite avant : une entrée
    basculée en privé, qui n'a plus son titre ; ou un sujet du backlog
    archivé au journal (B-0044, L1)."""
    f = ctx.memoire.fichiers.get(chemin)
    if f is not None and any(e.basculee and ancre.startswith(liens.ancre(e.id) + "--") for e in f.entrees):
        return True
    return chemin == ctx.projet.chemins.backlog and any(
        e.archivee and ancre.startswith(liens.ancre(e.id) + "--") for e in ctx.memoire.entrees("B"))


# Les titres qui citent un chemin renommé au format 2 changent d'ancre : une
# ancre ancienne, dans une demande gelée ou le journal, reste valide.
_ANCRES_RENOMMEES = [(liens.ancre(getattr(config.FORMAT_1, a)), liens.ancre(getattr(config.FORMAT_2, a)))
                     for a in ("politique", "garde_fous", "adaptateur", "lock", "prive_lock")]


def ancre_au_format_2(ancre: str) -> str:
    """Une ancre de titre écrite avant la migration, sous son nom au format 2."""
    for avant, apres in _ANCRES_RENOMMEES:
        ancre = ancre.replace(avant, apres)
    return re.sub(r"(?<![\w])memoire(?![\w])", "memory", ancre)


# Ce qui précède `:` sans désigner un dépôt : un schéma d'URL, un type de
# référence de la mémoire, une révision de git (`HEAD:chemin`).
SCHEMAS = {"http", "https", "ftp", "file", "mailto", "ssh", "git", "data", "commit", "fichier", "cmd", "url"}
REVISION = re.compile(r"^(?:[A-Z_]*HEAD|[0-9a-f]{7,40})(?:[~^]\d*)*$")


# Un dépôt que le projet lie par son adresse : `https://hôte/propriétaire/dépôt`,
# ou `git@hôte:propriétaire/dépôt.git`.
DEPOT_LIE = re.compile(r"(?:\bhttps?://[\w.-]+\.[A-Za-z]{2,}(?::\d+)?/|\bgit@[\w.-]+:)[\w.-]+/([\w.-]+?)(?:\.git)?"
                       r"(?=[/#?\s)\]>\"'`]|$)")


def depots_connus(ctx, textes) -> set[str]:
    """Les dépôts que le projet connaît déjà, sans réglage : ceux qu'il lie
    par leur adresse, dans les textes lus ou dans `.gitmodules`, et ceux que
    les garde-fous déclarent (`[references] repos`), pour un dépôt qu'aucune
    adresse ne nomme. L'outil s'adapte au projet : il ne demande pas ce que
    le projet dit déjà (Théo, J-2026-10-13-L)."""
    connus = set(ctx.projet.gf("references", "repos", defaut=[]) or [])
    for texte in [*textes, ctx.lire(".gitmodules") or ""]:
        connus |= {m.group(1).rstrip(".") for m in DEPOT_LIE.finditer(texte)}  # une adresse en fin de phrase
    return connus


def depot_non_declare(ctx, jeton: str, connus: set[str] | None = None) -> str | None:
    """Le dépôt d'un `depot:chemin` cité, si le projet ne le connaît pas
    (`depots_connus`) : son chemin n'est vérifié nulle part, et n'importe
    quelle chaîne `x:chemin` passerait (B-0052)."""
    m = re.match(r"^([A-Za-z0-9][\w.+-]*):([^:\s]*/[^\s]*|[^:\s/]+\.\w+)$", jeton.strip())
    if not m or m.group(1).lower() in SCHEMAS or m.group(2).startswith("//") or REVISION.match(m.group(1)):
        return None
    if connus is None:
        connus = set(ctx.projet.gf("references", "repos", defaut=[]) or [])
    return None if m.group(1) in connus else m.group(1)


def _verifier_chemin_cite(ctx, jeton: str, historique: bool = False) -> str | None:
    """Un chemin du dépôt cité entre accents graves. Ne juge que ce qui en a
    clairement la forme et commence par une racine du dépôt."""
    j = jeton.strip()
    if "/" not in j or any(c in INTERDITS_CHEMIN for c in j):
        return None
    if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", j) or j.startswith(("/", "../")):
        return None
    j = j.removeprefix("./")
    j = re.sub(r"(:\d+)+$", "", j).split("#", 1)[0]
    dossier = j.endswith("/")
    j = j.rstrip("/")
    if not j or j.split("/", 1)[0] not in _racines(ctx):
        return None
    # Un répertoire ignoré (`/tools/arbiters/`) ne se reconnaît qu'avec sa
    # barre finale : sans elle, git ne sait pas que c'est un répertoire.
    if _existe(ctx, j, historique) or _ignore(ctx.racine, j + "/" if dossier else j):
        return None
    return trad("chemin cité inexistant : `{jeton}`", jeton=jeton)


@controle("memoire.prive")
def prive(ctx, r):
    """Aucun identifiant privé dans un fichier public : le public ne référence
    jamais le privé. Un bloc de code et une archive sont publics comme le
    reste (B-0044, L3)."""
    moteur = ctx.projet.dossier_moteur.rstrip("/") + "/"
    for chemin in ctx.fichiers:
        if est_prive(chemin) or chemin.startswith(moteur):
            continue
        texte = ctx.lire(chemin)
        if texte is None or "\0" in texte[:4096] or len(texte) > 2_000_000:
            continue
        for ligne, contenu in enumerate(texte.splitlines(), start=1):
            for m in memoire.ID_RE.finditer(contenu):
                if m["prive"] and memoire.id_valide(m["type"], m["num"]):
                    r.erreur("memoire.prive", trad("identifiant privé `{ident}` dans un fichier public",
                                                   ident=m.group(0)), chemin, ligne)


# --------------------------------------------------------------------------
# Lecture prouvée (ADR-0008)
# --------------------------------------------------------------------------


@controle("memoire.lectures", base=True)
def lectures(ctx, r):
    """Une citation `ID@empreinte` ou `index@empreinte` ajoutée désigne une
    version que l'agent a pu lire (`socle.readings`, ADR-0023) ; une
    décision, une demande ou un sujet de backlog nouveaux prouvent ce qu'ils
    ont lu avant d'être écrits."""
    from socle import readings as lp

    mem, base = ctx.memoire, ctx.memoire_base
    defs = mem.definitions()
    nouveaux = set(defs) - set(base.definitions())
    plage = lp.Plage(ctx.racine, base, mem, [c["sha"] for c in ctx.commits])

    for chemin, texte in sorted(textes_scannes(ctx).items()):
        avant = ctx.lire_base(chemin) or ""
        for ident, h, ligne in memoire.citations(texte):
            soi = lp.entree_englobante(mem, chemin, ligne)
            if ident not in defs or lp.deja_citee(soi, f"{ident}@{h}", base, avant):
                continue
            if not lp.entree_lue(plage, chemin, soi, ident, h):
                r.erreur("memoire.lectures", trad("`{ident}@{h}` ne correspond pas à la version actuelle de "
                                                  "{ident} (lue avant un changement, ou inventée) : la relire, "
                                                  "`python3 .socle/socle show {ident}`, et citer l'empreinte "
                                                  "affichée", ident=ident, h=h), chemin, ligne)
        for index, h, ligne in memoire.citations_index(texte):
            soi = lp.entree_englobante(mem, chemin, ligne)
            if lp.deja_citee(soi, f"{index}@{h}", base, avant):
                continue
            if not lp.index_lu(plage, chemin, soi, index, h):
                r.erreur("memoire.lectures", trad("`{index}@{h}` ne correspond à aucune version récente de "
                                                  "l'index : le relire, `python3 .socle/socle show --index "
                                                  "{index}`, et citer l'empreinte affichée", index=index, h=h),
                         chemin, ligne)

    # Ce que les entrées nouvelles doivent prouver avoir lu.
    for ident in sorted(nouveaux):
        e = defs[ident][0]
        if e.archivee:
            continue
        if e.depuis and all(d in defs and defs[d][0].basculee for d in e.depuis):
            continue  # la copie privée d'une entrée basculée : ce n'est pas une entrée nouvelle (B-0029)
        if e.type == "ADR" and not any(i == "decisions" for i, _, _ in memoire.citations_index(e.texte)):
            r.erreur("memoire.lectures", trad("décision nouvelle `{ident}` sans `lu : decisions@…` : consulter "
                                              "l'index des décisions avant d'en ajouter une (`socle show "
                                              "--index decisions`)", ident=ident), e.fichier, e.ligne)
        if e.type == "B" and not any(i == "backlog" for i, _, _ in memoire.citations_index(e.texte)):
            r.erreur("memoire.lectures", trad("sujet nouveau `{ident}` sans `lu : backlog@…` : consulter le "
                                              "backlog avant d'y ajouter, pour ne pas dupliquer (`socle show "
                                              "--index backlog`)", ident=ident), e.fichier, e.ligne)
        if e.type in ("ADR", "D"):
            prouves = {i for i, _, _ in memoire.citations(e.texte)}
            for cite in sorted({i for i, _ in memoire.mentions(e.texte)} - prouves - {ident}):
                r.erreur("memoire.lectures", trad("`{ident}` s'appuie sur `{cite}` sans montrer l'avoir lu : "
                                                  "citer `{cite}@<empreinte>`, l'empreinte que donne `socle "
                                                  "show {cite}`", ident=ident, cite=cite), e.fichier, e.ligne)


# --------------------------------------------------------------------------
# Preuves, backlog
# --------------------------------------------------------------------------

TYPES_PREUVE = {"commit", "fichier", "cmd", "id"}


@controle("memoire.preuves")
def preuves(ctx, r):
    """Un fait mesuré pointe vers sa preuve ; un fait réfuté garde sa trace ; un
    fait validé cite la demande que l'humain a validée."""
    par_id = {d.id: d for d in ctx.demandes if d.id}
    for e in ctx.memoire.entrees("F"):
        if e.statut == "mesure":
            if not {t for t, _ in e.refs("preuve")} & TYPES_PREUVE:
                r.erreur("memoire.preuves", trad("`{id}` est « mesuré » sans `preuve` (commit:, fichier:, cmd: "
                                                 "ou identifiant)", id=e.id), e.fichier, e.ligne)
        elif e.statut == "refute":
            if not e.barre:
                r.erreur("memoire.preuves", trad("`{id}` réfuté : son titre se barre (`~~…~~`), il ne s'efface "
                                                 "pas", id=e.id), e.fichier, e.ligne)
            if not {t for t, _ in e.refs("refutation", "preuve")} & TYPES_PREUVE:
                r.erreur("memoire.preuves", trad("`{id}` réfuté sans `refutation` qui pointe vers la mesure",
                                                 id=e.id), e.fichier, e.ligne)
        elif e.statut == "valide":
            cites = [c for t, c in e.refs("validation") if t == "id" and c.lstrip("P").startswith("D-")]
            if not cites:
                r.erreur("memoire.preuves", trad("`{id}` « validé » sans `validation : D-NNNN` — ce statut ne "
                                                 "s'écrit que par l'humain, via une demande", id=e.id), e.fichier, e.ligne)
            for c in cites:
                d = par_id.get(c)
                if d is None or not d.validee:
                    r.erreur("memoire.preuves", trad("`{id}` cite `{demande}`, qui n'a pas de réponse « valider »",
                                                     id=e.id, demande=c), e.fichier, e.ligne)


@controle("memoire.collisions", base=True)
def collisions(ctx, r):
    """Un identifiant que la branche définit et que la branche par défaut a
    pris aussi depuis leur divergence, pour une autre entrée, serait défini
    deux fois à la fusion (ADR-0026) : dit avant, avec la commande qui répare."""
    from socle import identifiers as identifiants

    bases = identifiants.bases_a_comparer(ctx.racine, ctx.base)
    for ident, ici, la_bas in identifiants.collisions(ctx.racine, ctx.tete, ctx.memoire, bases):
        r.erreur("memoire.collisions", trad("`{ident}` est pris aussi sur la branche par défaut, depuis que "
                                            "cette branche s'en est séparée, pour « {titre} » : à la fusion, "
                                            "il serait défini deux fois. `python3 .socle/socle renumber "
                                            "{ident}` lui donne le prochain libre et le reporte",
                                            ident=ident, titre=la_bas.titre), ici.fichier, ici.ligne)


@controle("memoire.backlog")
def backlog(ctx, r):
    """Chaque sujet a une origine ; un sujet clos a une référence, et il est rangé avec les clos."""
    en_dossier = ctx.projet.chemins.backlog_en_dossier
    for e in ctx.memoire.entrees("B"):
        if e.basculee:
            continue
        if not e.refs("origine"):
            r.erreur("memoire.backlog", trad("`{id}` sans `origine` (entrée de journal, commit ou demande)",
                                             id=e.id), e.fichier, e.ligne)
        clos = e.statut in memoire.BACKLOG_CLOS
        if clos and not e.refs("ref"):
            r.erreur("memoire.backlog", trad("`{id}` est clos (« {statut} ») sans `ref` vers ce qui l'a clos",
                                             id=e.id, statut=e.statut), e.fichier, e.ligne)
        # Au format 3, un sujet clos quitte les ouverts (ADR-0030).
        if en_dossier and memoire.couche_attendue(e.fichier) == "backlog" and clos != memoire.parmi_les_clos(e.fichier):
            r.erreur("memoire.backlog", trad("`{id}` est clos (« {statut} ») mais reste parmi les sujets ouverts : "
                                             "`python3 .socle/socle archive` le range dans `{dossier}/`",
                                             id=e.id, statut=e.statut, dossier=memoire.DOSSIER_CLOS) if clos else
                     trad("`{id}` est rangé parmi les sujets clos alors qu'il est « {statut} » : `python3 "
                          ".socle/socle archive` le remet parmi les ouverts", id=e.id, statut=e.statut),
                     e.fichier, e.ligne)


# --------------------------------------------------------------------------
# Budgets, péremption, retard
# --------------------------------------------------------------------------


@controle("memoire.budgets")
def budgets(ctx, r):
    """Chaque couche et le fichier d'instructions ont un plafond de taille."""
    budgets = ctx.projet.gf("budgets", defaut={}) or {}
    couverts = set()
    # La zone privée suit les budgets de la zone publique : mêmes formats,
    # mêmes contrôles (cadrage, règles de classement, point 5).
    ch = ctx.projet.chemins
    miroirs = {c: ch.memoire + "/" + memoire.hors_zone_privee(c) for c in ctx.fichiers if est_prive(c)}
    # Un sujet rangé avec les clos garde le plafond d'un sujet (ADR-0030).
    miroirs = {c: memoire.hors_des_clos(miroirs.get(c, c)) for c in ctx.fichiers
               if c in miroirs or memoire.parmi_les_clos(c)}
    for motif, b in budgets.items():
        vises = set(outils.filtrer(ctx.fichiers, [motif])) | {c for c, m in miroirs.items() if outils.correspond(m, [motif])}
        for chemin in sorted(vises):
            couverts.add(chemin)
            texte = ctx.lire(chemin) or ""
            octets = len(texte.encode("utf-8"))
            lignes = texte.count("\n") + (0 if texte.endswith("\n") or not texte else 1)
            if "max_bytes" in b and octets > b["max_bytes"]:
                r.erreur("memoire.budgets", trad("{octets} octets pour un budget de {budget} ({motif}) : archiver "
                                                 "dans le journal", octets=octets, budget=b['max_bytes'], motif=motif), chemin)
            if "max_lines" in b and lignes > b["max_lines"]:
                r.erreur("memoire.budgets", trad("{lignes} lignes pour un budget de {budget} ({motif}) : archiver "
                                                 "dans le journal", lignes=lignes, budget=b['max_lines'], motif=motif), chemin)
    # Le fichier d'instructions est AGENTS.md ; tant qu'une adoption garde
    # CLAUDE.md comme source (renommage en attente), c'est lui qui est relu.
    instructions = [config.INSTRUCTIONS]
    if (ctx.lire("CLAUDE.md") or "").strip() not in ("", "@AGENTS.md"):
        instructions.append("CLAUDE.md")
    for chemin in list(ctx.memoire.fichiers) + instructions:
        if chemin in ctx.fichiers and chemin not in couverts:
            r.erreur("memoire.budgets", trad("aucun budget ne couvre ce fichier (`[budgets]` des garde-fous)"), chemin)


def date_derniere_modif(ctx, chemin: str) -> float | None:
    if ctx.tete is None and chemin in ctx._cache.setdefault("sales", _sales(ctx)):
        return time.time()
    rev = ctx.rev_commit
    if not outils.a_des_commits(ctx.racine):
        return time.time()
    sortie = outils.git(ctx.racine, "log", "-1", "--format=%ct", rev, "--", chemin, check=False).strip()
    return float(sortie) if sortie else None


def _sales(ctx) -> set[str]:
    if not outils.a_des_commits(ctx.racine):
        return set(ctx.fichiers)
    sortie = outils.git(ctx.racine, "status", "--porcelain", "-z", check=False)
    return {e[3:] for e in sortie.split("\0") if len(e) > 3}


@controle("memoire.peremption")
def peremption(ctx, r):
    """Un chantier actif qui ne bouge plus est signalé — un avertissement, pas un échec."""
    jours = ctx.projet.gf("staleness", "active_days", defaut=7)
    chemin = ctx.projet.chemins.actif
    if chemin not in ctx.fichiers:
        return
    t = date_derniere_modif(ctx, chemin)
    if t is None:
        return
    age = (time.time() - t) / 86400
    if age > jours:
        r.avertir("memoire.peremption", trad("chantier actif inchangé depuis {age} jours (seuil : {jours})",
                                             age=format(age, '.0f'), jours=jours), chemin)


@controle("memoire.retard", etages=("agent",), base=True)
def retard(ctx, r):
    """Du code a changé et la mémoire non : la fin de tour attend sa mise à jour."""
    if not ctx.projet.gf("memory", "require_update_on_code_change", defaut=True):
        return
    code = outils.filtrer(ctx.changes, ctx.projet.chemins_code())
    if code and not any(memoire.est_memoire(c) for c in ctx.changes):
        r.erreur("memoire.retard", trad("{n} fichier(s) de code changé(s) depuis la base et aucun de "
                                        "`{memoire}/` : mettre à jour le chantier actif ou le journal avant de "
                                        "conclure", n=len(code), memoire=ctx.projet.chemins.memoire))


# --------------------------------------------------------------------------
# Ajout seul : comparé à la base
# --------------------------------------------------------------------------


def _corps_sans_meta(e: memoire.Entree) -> str:
    """Le texte de l'entrée sans son titre ni sa ligne de métadonnées, celle
    qui suit le titre. Une citation du corps en fait partie : la réécrire,
    c'est réécrire la décision (relevé de la passe de recul, D)."""
    lignes = e.texte.splitlines()[1:]
    j = 0
    while j < len(lignes) and not lignes[j].strip():
        j += 1
    while j < len(lignes) and lignes[j].lstrip().startswith(">"):
        j += 1
    return "\n".join(lignes[j:]).strip()


def _norm(t: str) -> str:
    return "\n".join(l.rstrip() for l in t.strip().splitlines())


def _sans_niveaux(t: str) -> str:
    """Le texte, ses titres ramenés à un même niveau : la migration au format
    3 remonte d'un niveau les sous-titres d'un sujet, sans rien en changer
    d'autre (B-0064)."""
    return re.sub(r"(?m)^#{1,6} ", "# ", _norm(t))


@controle("memoire.ajout-seul", base=True)
def ajout_seul(ctx, r):
    """Journal et décisions en ajout seul ; un fait ne disparaît pas, ne change
    qu'avec une nouvelle preuve, et se barre quand il est réfuté. La mémoire
    privée aussi, relue à la base (B-0044, L3)."""
    from socle import private as prive

    _comparer(ctx, r, ctx.memoire_base.definitions(), ctx.memoire.definitions())
    if prive.mode(ctx.projet):
        avant, apres = prive.memoire_privee_a(ctx.projet, ctx.base), prive.memoire_privee(ctx)
        if avant is None or apres is None:
            r.indisponible("memoire.ajout-seul", trad("mémoire privée illisible ici : son ajout seul n'est pas "
                                                      "vérifié"))
        else:
            _comparer(ctx, r, {i: d for i, d in avant.definitions().items() if i.startswith("P")},
                      apres.definitions())

    reponses_base = {c for c in ctx.fichiers_base if memoire.est_reponse(c)}
    for c in sorted(reponses_base):
        if ctx.lire(c) != ctx.lire_base(c):
            r.erreur("memoire.ajout-seul", trad("réponse humaine modifiée ou supprimée : elle est définitive"), c)


def _comparer(ctx, r, avant: dict, apres: dict):
    for ident, defs in avant.items():
        a = defs[0]
        b = apres.get(ident, [None])[0]
        if a.basculee:
            if b is None or not b.basculee or _norm(a.texte) != _norm(b.texte):
                r.erreur("memoire.ajout-seul", trad("`{ident}` basculée dans la mémoire privée : elle reste "
                                                    "telle quelle", ident=ident),
                         (b or a).fichier, (b or a).ligne)
            continue
        if b is not None and b.basculee:
            _bascule(ctx, r, a, b)
            continue
        if a.type == "J":
            if b is None:
                r.erreur("memoire.ajout-seul", trad("entrée de journal `{ident}` supprimée (le journal est en "
                                                    "ajout seul)", ident=ident), a.fichier, a.ligne)
            elif _norm(a.texte) != _norm(b.texte) and not _seulement_ajouts(a.texte, b.texte):
                r.erreur("memoire.ajout-seul", trad("entrée de journal `{ident}` modifiée (le journal est en "
                                                    "ajout seul)", ident=ident), b.fichier, b.ligne)
        elif a.type == "ADR":
            if b is None:
                r.erreur("memoire.ajout-seul", trad("décision `{ident}` supprimée (une décision se remplace, "
                                                    "elle ne s'efface pas)", ident=ident), a.fichier, a.ligne)
                continue
            if _norm(_corps_sans_meta(a)) != _norm(_corps_sans_meta(b)) or a.titre != b.titre:
                r.erreur("memoire.ajout-seul", trad("décision `{ident}` réécrite : seul son statut peut "
                                                    "changer, une décision nouvelle la remplace", ident=ident), b.fichier, b.ligne)
            if a.statut != b.statut and (a.statut, b.statut) not in TRANSITIONS_ADR:
                r.erreur("memoire.ajout-seul", trad("décision `{ident}` : passage « {statut} » → « {apres} » "
                                                    "interdit", ident=ident, statut=a.statut, apres=b.statut), b.fichier, b.ligne)
            if b.statut == "remplacee" and not [c for t, c in b.refs("remplacee-par") if t == "id"]:
                r.erreur("memoire.ajout-seul", trad("décision `{ident}` remplacée sans `remplacée-par : "
                                                    "ADR-NNNN`", ident=ident), b.fichier, b.ligne)
        elif a.type == "F":
            if b is None:
                r.erreur("memoire.ajout-seul", trad("fait `{ident}` effacé : un fait se barre (réfuté) ou "
                                                    "s'archive dans le journal, jamais ne disparaît",
                                                    ident=ident), a.fichier, a.ligne)
                continue
            if b.archivee:
                continue
            if _norm(a.texte) == _norm(b.texte):
                continue
            nouvelles = set(b.refs("preuve", "refutation", "validation")) - set(a.refs("preuve", "refutation", "validation"))
            if not nouvelles:
                r.erreur("memoire.ajout-seul", trad("fait `{ident}` modifié sans référence de preuve nouvelle",
                                                    ident=ident), b.fichier, b.ligne)
            if b.statut == "refute" and a.statut != "refute":
                if _norm(a.corps) and _norm(a.corps) not in _norm(b.corps):
                    r.erreur("memoire.ajout-seul", trad("fait `{ident}` réfuté : son texte se garde, barré ; "
                                                        "il ne se réécrit pas", ident=ident), b.fichier, b.ligne)
        elif a.type == "B":
            if b is None:
                r.erreur("memoire.ajout-seul", trad("sujet `{ident}` disparu du backlog sans archive dans le "
                                                    "journal", ident=ident), a.fichier, a.ligne)
            elif b.archivee and b.statut not in memoire.BACKLOG_CLOS:
                r.erreur("memoire.ajout-seul", trad("sujet `{ident}` archivé sans être clos", ident=ident), b.fichier, b.ligne)
        elif a.type == "D":
            if b is None:
                r.erreur("memoire.ajout-seul", trad("demande `{ident}` supprimée (la retirer : `retirée : "
                                                    "<raison>` dans ses métadonnées)", ident=ident), a.fichier, a.ligne)


def _bascule(ctx, r, a: memoire.Entree, b: memoire.Entree):
    """Une entrée publique basculée dans la mémoire privée (B-0029) : une copie
    privée qui cite `depuis : <identifiant>` en reprend le texte, sans quoi la
    bascule serait un effacement."""
    from socle import private as prive

    privee = prive.memoire_privee(ctx) if prive.mode(ctx.projet) else None
    if privee is None and prive.mode(ctx.projet):
        r.avertir("memoire.ajout-seul", trad("`{id}` basculée : sa copie privée ne se lit pas ici", id=a.id), b.fichier, b.ligne)
        return
    copies = [e for e in privee.entrees() if e.prive and a.id in e.depuis] if privee else []
    if not copies:
        r.erreur("memoire.ajout-seul", trad("`{id}` basculée sans copie privée qui la reprenne (`depuis : "
                                            "{id}`) : son contenu serait perdu ; `socle private move` fait les "
                                            "deux", id=a.id), b.fichier, b.ligne)
        return
    if not any(_sans_niveaux(a.corps) in _sans_niveaux(c.corps) and a.titre == c.titre for c in copies):
        r.erreur("memoire.ajout-seul", trad("`{id}` basculée : sa copie privée n'en reprend ni le titre ni le "
                                            "texte", id=a.id),
                 b.fichier, b.ligne)


def _seulement_ajouts(avant: str, apres: str) -> bool:
    """Une entrée de journal qui reçoit une archive imbriquée à la suite de son
    texte reste en ajout seul ; un ajout commence sur une ligne nouvelle,
    jamais au milieu d'une phrase (relevé de la passe de recul, D)."""
    a, b = _norm(avant), _norm(apres)
    return b == a or b.startswith(a + "\n")


# --------------------------------------------------------------------------
# Demandes
# --------------------------------------------------------------------------


@controle("demandes.contrat")
def contrat(ctx, r):
    """Toute demande en attente est autonome : huit champs, aucun identifiant nu."""
    for d in ctx.demandes:
        if d.reponse is not None:
            continue  # gelée : elle a été lintée quand elle a été écrite
        for faute in demandes.linter(d, ctx.projet):
            r.erreur("demandes.contrat", faute, d.chemin)


@controle("demandes.reponses")
def reponses(ctx, r):
    """Une réponse porte sur le texte exact de sa demande et en est une réponse possible."""
    for d in ctx.demandes:
        for faute in demandes.verifier_reponse(d):
            r.erreur("demandes.reponses", faute, d.chemin_reponse or d.chemin)
    for c in ctx.fichiers:
        if memoire.est_reponse(c):
            if memoire.demande_de_reponse(c) not in ctx.fichiers:
                r.erreur("demandes.reponses", trad("réponse sans demande"), c)


@controle("instructions.source-unique")
def source_unique(ctx, r):
    """Un seul fichier d'instructions fait foi : `AGENTS.md`, que `CLAUDE.md`
    importe en une ligne ; ou, sans `AGENTS.md`, `CLAUDE.md` qui porte la
    section du socle, quand l'installeur l'a gardé parce que le projet le
    nomme (B-0049)."""
    if config.INSTRUCTIONS not in ctx.fichiers:
        if "CLAUDE.md" in ctx.fichiers and config.DEBUT_SOCLE in (ctx.lire("CLAUDE.md") or ""):
            return
        r.erreur("instructions.source-unique", trad("AGENTS.md absent, et CLAUDE.md ne porte pas la section du "
                                                    "socle : aucun fichier d'instructions ne fait foi"))
        return
    if "CLAUDE.md" in ctx.fichiers:
        texte = (ctx.lire("CLAUDE.md") or "").strip()
        if texte != "@AGENTS.md":
            r.erreur("instructions.source-unique", trad("CLAUDE.md doit contenir la seule ligne `@AGENTS.md` "
                                                        "(aucune copie à synchroniser)"), "CLAUDE.md")

"""Les migrations du format des fichiers du projet (mémoire, politique,
garde-fous) d'une version du socle à la suivante.

Le verrou du moteur note le format (`format = N`). À la mise à jour,
l'installeur applique, dans l'ordre, chaque migration de N à la version
courante : un script, jamais un merge à la main. Une migration manquante
arrête la mise à jour au lieu de laisser un format qu'aucun contrôle ne lit.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Callable

from socle import config, utils as outils
from socle.messages import trad

# Un chemin du format 1 dans un texte : la mémoire, ou un fichier de `.socle/`
# renommé. Ce qui suit le chemin (guillemet, espace, parenthèse…) le termine.
CHEMIN_1 = re.compile(r"(?<![\w./-])(?P<pre>(?:\.\./)+|/)?(?P<chemin>memoire/[^\s\"'`)\]>,;]*|"
                      r"\.socle/(?:moteur\.lock|politique\.toml|garde-fous\.toml|"
                      r"adaptateur\.toml|prive\.lock|moteur(?=/|[\s\"'`)\]>,;]|$))[^\s\"'`)\]>,;]*)")


def traduire_texte(texte: str) -> str:
    """Les chemins du format 1 d'un texte, sous leurs noms du format 2 ; un
    lien relatif (`../memoire/…`) ou un motif ancré (`/memoire/prive/`) aussi."""
    return CHEMIN_1.sub(lambda m: (m["pre"] or "") + config.traduire(m["chemin"], vers=2), texte)


def _vers_format_2(cible: Path) -> list[str]:
    """B-0032 : les chemins passent en anglais (`memory/`, `canonical.md`,
    `requests/`, `policy.toml`, `guardrails.toml`…). Les fichiers sont
    renommés (`git mv`, l'historique les suit) ; les chemins sont traduits
    dans la configuration et dans la documentation hors mémoire. La mémoire
    n'est pas réécrite : le journal est en ajout seul, une demande répondue
    est gelée, et les anciens chemins qu'elles citent restent valides par
    alias."""
    res = []
    # Les fichiers suivis par git, et eux seuls : un fichier pas encore
    # commité se déplace à la main, sans quoi `git mv` le laisserait derrière.
    suivis = set(outils.git(cible, "ls-files", "-z", check=False).split("\0")) - {""} \
        if outils.est_depot(cible) else set()

    def deplacer(de: str, vers: str):
        a, b = cible / de, cible / vers
        if not a.exists() and not a.is_symlink():
            return
        if b.exists():
            raise RuntimeError(trad("migration arrêtée : {vers} existe déjà, {de} n'y est pas déplacé — "
                                    "fusionner les deux à la main, puis relancer", vers=vers, de=de))
        b.parent.mkdir(parents=True, exist_ok=True)
        if de in suivis:
            outils.git(cible, "mv", de, vers)
        else:
            shutil.move(str(a), str(b))

    # 1. La configuration du socle.
    for de, vers in ((".socle/moteur.lock", ".socle/engine.lock"), (".socle/politique.toml", ".socle/policy.toml"),
                     (".socle/garde-fous.toml", ".socle/guardrails.toml"),
                     (".socle/adaptateur.toml", ".socle/adapter.toml"), (".socle/prive.lock", ".socle/private.lock")):
        if (cible / de).exists():
            deplacer(de, vers)
            res.append(f"{de} → {vers}")
    if (cible / ".socle/moteur").is_dir():
        if (cible / ".socle/engine").exists():
            shutil.rmtree(cible / ".socle/engine")
        for f in sorted(x for x in suivis if x.startswith(".socle/moteur/")):
            deplacer(f, config.traduire(f, vers=2))
        if (cible / ".socle/moteur").exists():
            shutil.rmtree(cible / ".socle/moteur")
        res.append(".socle/moteur/ → .socle/engine/")

    # 2. La mémoire, fichier par fichier. Le clone du dépôt privé (mode
    # compagnon) se déplace en bloc, puis ses fichiers se renomment dedans :
    # à commiter dans le dépôt privé, puis `socle private lock`.
    memoire_1 = cible / "memoire"
    if memoire_1.is_dir():
        prive_1 = memoire_1 / "prive"
        compagnon = (prive_1 / ".git").exists()
        if compagnon:
            (cible / "memory").mkdir(exist_ok=True)
            shutil.move(str(prive_1), str(cible / "memory/private"))
            prive_2 = cible / "memory/private"
            for dossier, sous, noms in os.walk(prive_2):
                sous[:] = [s for s in sous if s != ".git"]
                for n in noms:
                    rel = str((Path(dossier) / n).relative_to(prive_2)).replace(os.sep, "/")
                    neuf = config.traduire("memoire/prive/" + rel, vers=2)[len("memory/private/"):]
                    if neuf != rel:
                        (prive_2 / neuf).parent.mkdir(parents=True, exist_ok=True)
                        outils.git(prive_2, "mv", "-k", rel, neuf)
            res.append(trad("le dépôt privé, cloné dans memory/private/ : ses fichiers sont renommés, à "
                            "commiter dans le dépôt privé, puis `socle private lock`"))
        for dossier, sous, noms in os.walk(memoire_1):
            for n in noms:
                rel = str((Path(dossier) / n).relative_to(cible)).replace(os.sep, "/")
                deplacer(rel, config.traduire(rel, vers=2))
        # L'ancien dossier ne se supprime que vide : un fichier resté là est
        # une perte, pas un reste.
        restes = [str(Path(d, n).relative_to(cible)) for d, _, noms in os.walk(memoire_1) for n in noms]
        if restes:
            raise RuntimeError(trad("migration arrêtée : des fichiers restent dans memoire/ — {restes}",
                                    restes=", ".join(restes[:5])))
        shutil.rmtree(memoire_1)
        res.append("memoire/ → memory/ (canonical.md, active.md, requests/, private/, *.answer.toml)")

    # 3. Les chemins cités par la configuration et la documentation ; ni la
    # mémoire, ni le moteur (son format décrit les deux).
    reecrits = []
    moteur = config.lire_toml(outils.lire_a(cible, None, config.FORMAT_2.lock) or "").get("engine_dir", "")
    hors = tuple(x for x in ("memory/", ".socle/engine/", moteur.rstrip("/") + "/" if moteur else "") if x)
    for f in sorted(set(outils.fichiers_courants(cible)) if outils.est_depot(cible) else []):
        if not (f in (".gitignore", ".gitattributes", ".github/CODEOWNERS") or f.startswith(".socle/")
                and f.endswith((".toml", ".lock")) or f.endswith(".md") and not f.startswith(hors)):
            continue
        p = cible / f
        if not p.is_file():
            continue
        avant = p.read_text(encoding="utf-8")
        apres = traduire_texte(avant)
        if apres != avant:
            p.write_text(apres, encoding="utf-8")
            reecrits.append(f)
    if reecrits:
        res.append(trad("chemins traduits dans {n} fichier(s) : {liste}",
                        n=len(reecrits), liste=', '.join(reecrits[:8]))
                   + (" …" if len(reecrits) > 8 else ""))
    config.oublier_formats()
    return res


# Ce qui ouvre un titre markdown ; un sujet devenu fichier remonte d'un niveau.
TITRE = re.compile(r"^##+ ")
# Le plafond d'un sujet du backlog, une fois chacun dans son fichier.
BUDGET_SUJET = 8000


def _vers_format_3(cible: Path) -> list[str]:
    """ADR-0025 : le backlog devient un dossier, un fichier par sujet, dans
    la zone publique et dans la zone privée. Chaque sujet garde son texte, ses
    titres remontés d'un niveau ; le fichier unique est retiré, et son plafond
    devient un plafond par sujet. Rien à faire là où le backlog est déjà un
    dossier : la migration se relance sans dommage."""
    from socle import memory as memoire

    res = []
    f2, f3 = config.FORMAT_2, config.FORMAT_3
    suivis = set(outils.git(cible, "ls-files", "-z", check=False).split("\0")) - {""} \
        if outils.est_depot(cible) else set()
    for unique, dossier in ((f2.backlog, f3.backlog), (f2.dans_prive(f2.backlog), f3.dans_prive(f3.backlog))):
        p = cible / unique
        if not p.is_file():
            continue
        texte = p.read_text(encoding="utf-8")
        if not memoire.lisible(texte):
            raise RuntimeError(trad("migration arrêtée : {unique} est chiffré ici ; le déchiffrer, puis "
                                    "relancer", unique=unique))
        f = memoire.analyser(unique, texte)
        entete = texte.splitlines()[0] if memoire.ENTETE_FICHIER.search(texte.splitlines()[0] if texte else "") \
            else "<!-- socle: couche=backlog zone=publique -->"
        sujets = [e for e in f.entrees if e.type == "B" and e.niveau == 2]
        for e in sujets:
            lignes = [(l[1:] if not code and TITRE.match(l) else l) for _, l, code in memoire.lignes_hors_code(e.texte)]
            nom = f"{e.id}-{memoire.nom_de_fichier(e.titre)}.md"
            outils.ecrire(cible / dossier / nom, entete + "\n" + "\n".join(lignes).rstrip("\n") + "\n")
        if unique in suivis:
            outils.git(cible, "rm", "-q", unique)
            outils.git(cible, "add", "--", dossier)
        else:
            p.unlink()
        res.append(trad("{unique} → {dossier}/ : {n} sujet(s), un fichier chacun",
                        unique=unique, dossier=dossier, n=len(sujets)))
    gf = cible / f2.garde_fous
    if gf.is_file():
        texte = gf.read_text(encoding="utf-8")
        neuf = re.sub(rf'(?m)^(["\']){re.escape(f2.backlog)}\1\s*=\s*\{{[^}}]*\}}',
                      f'"{f3.backlog}/*.md" = {{ max_bytes = {BUDGET_SUJET} }}', texte)
        if neuf != texte:
            gf.write_text(neuf, encoding="utf-8")
            res.append(trad("plafond du backlog : {budget} octets par sujet", budget=BUDGET_SUJET))
    config.oublier_formats()
    return res


# Version courante du format. Une migration `MIGRATIONS[n]` fait passer un
# projet du format n au format n + 1, et rend ce qu'elle a fait.
FORMAT = 3
MIGRATIONS: dict[int, Callable[[Path], list[str]]] = {1: _vers_format_2, 2: _vers_format_3}


def migrer(cible: Path, depuis: int, jusqua: int | None = None) -> list[str]:
    jusqua = FORMAT if jusqua is None else jusqua
    res = []
    for v in range(depuis, jusqua):
        f = MIGRATIONS.get(v)
        if f is None:
            raise RuntimeError(trad("aucune migration du format {avant} au format {apres} : mise à jour arrêtée",
                                    avant=v, apres=v + 1))
        res += [trad("format {avant} → {apres} : {ligne}", avant=v, apres=v + 1, ligne=ligne)
                for ligne in f(cible)] or [trad("format {avant} → {apres}", avant=v, apres=v + 1)]
    return res

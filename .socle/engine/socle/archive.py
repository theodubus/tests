"""Archivage : ce qui sort d'une couche bornée part dans le journal, avec son
identifiant, pour que toute référence vers lui reste vivante."""

from __future__ import annotations

import re
from datetime import date

from pathlib import Path

from socle import config, language as langue, memory as memoire, utils as outils
from socle.messages import trad

TITRE = re.compile(r"^#{1,5} ")


def archiver_backlog(projet: config.Projet) -> int:
    racine = projet.racine
    ch = config.chemins(racine)
    if ch.backlog_en_dossier:
        deplaces = ranger_backlog(racine)
        for avant, apres in deplaces:
            print(f"{avant} → {apres}")
        print(trad("{n} sujet(s) rangé(s) : les clos dans `{dossier}/`, les ouverts hors de lui",
                   n=len(deplaces), dossier=memoire.DOSSIER_CLOS) if deplaces else trad("le backlog est déjà rangé"))
        return 0
    chemin = racine / ch.backlog
    if not chemin.is_file():
        print(trad("pas de backlog"))
        return 0
    texte = chemin.read_text(encoding="utf-8")
    f = memoire.analyser(ch.backlog, texte)
    clos = [e for e in f.entrees if e.type == "B" and e.statut in memoire.BACKLOG_CLOS and e.refs("ref")]
    if not clos:
        print(trad("aucun sujet clos à archiver"))
        return 0
    jour = date.today().isoformat()
    lg = langue.du_projet(projet)
    mem = memoire.Memoire.charger(racine)
    ident = mem.prochain_id("J", date=jour)
    blocs = []
    for e in clos:
        # Le sujet descend d'un niveau, sous-titres compris (hors des blocs de
        # code) : il devient un sous-titre de l'entrée, et les siens le
        # restent au lieu de devenir ses frères (B-0044, L1).
        lignes = [("#" + l if not code and TITRE.match(l) else l) for _, l, code in memoire.lignes_hors_code(e.texte)]
        blocs.append("\n".join(lignes))
        texte = texte.replace(e.texte, "", 1)
    texte = "\n".join(l for l in _sans_vides_multiples(texte.splitlines())).rstrip("\n") + "\n"
    chemin.write_text(texte, encoding="utf-8")
    ids = ", ".join(e.id for e in clos)
    titre = langue.mot(langue.TEXTES, "archive-backlog", lg)
    entree = f"\n## {ident} — {titre} : {ids}\n\n" + "\n\n".join(blocs) + "\n"
    journal = memoire.fichier_journal(racine / ch.journal, jour[:7], projet.budget_octets(f"{ch.journal}/{jour[:7]}.md"),
                                      len(entree.encode("utf-8")))
    if not journal.is_file():
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(f"{langue.entete_fichier('journal', 'publique', lg)}\n"
                           f"# {langue.mot(langue.TEXTES, 'titre-journal', lg)} — {jour[:7]}\n", encoding="utf-8")
    journal.write_text(journal.read_text(encoding="utf-8").rstrip("\n") + "\n" + entree, encoding="utf-8")
    print(trad("{n} sujet(s) archivé(s) dans {ident} ({journal})",
               n=len(clos), ident=ident, journal=journal.relative_to(racine)))
    return 0


def ranger_backlog(racine: Path) -> list[tuple[str, str]]:
    """Au format 3, range chaque sujet du backlog selon son statut : un sujet
    clos dans le sous-dossier des clos, un sujet ouvert hors de lui, dans la
    zone publique comme dans la privée (ADR-0030). Un déplacement suivi par
    le dépôt est indexé ; dans le dépôt compagnon, il reste à y commiter.
    Rend les déplacements, (avant, après) ; idempotent."""
    if not config.chemins(racine).backlog_en_dossier:
        return []
    suivis = set(outils.git(racine, "ls-files", "-z", check=False).split("\0")) - {""} \
        if outils.est_depot(racine) else set()
    res = []
    for e in memoire.Memoire.charger(racine).entrees("B"):
        if e.basculee or memoire.couche_attendue(e.fichier) != "backlog" or e.fichier.endswith("/backlog.md"):
            continue
        clos = e.statut in memoire.BACKLOG_CLOS
        if clos == memoire.parmi_les_clos(e.fichier):
            continue
        dossier, nom = e.fichier.rsplit("/", 1)
        cible = f"{dossier}/{memoire.DOSSIER_CLOS}/{nom}" if clos else memoire.hors_des_clos(e.fichier)
        (racine / cible).parent.mkdir(parents=True, exist_ok=True)
        (racine / e.fichier).rename(racine / cible)
        if e.fichier in suivis:
            outils.git(racine, "add", "-A", "--", e.fichier, cible)
        res.append((e.fichier, cible))
    return res


def _sans_vides_multiples(lignes):
    vide = False
    for l in lignes:
        if not l.strip():
            if vide:
                continue
            vide = True
        else:
            vide = False
        yield l

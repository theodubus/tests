"""Le mariage avec BMAD Method (ADR-0032) : ce que le socle garde de ce que
BMAD produit, sans le recopier.

- `bmad.reports` : un travail que BMAD reporte (sa liste des travaux
  reportés) entre au backlog du socle, la seule liste des trouvailles ;
  `socle bmad-import` l'y fait entrer, et le report s'y reconnaît à son
  empreinte.
- `bmad.lectures` : une décision d'architecture de BMAD citée avec son
  empreinte (`AD-n@empreinte`) dans la mémoire l'est dans sa version
  actuelle (B-0072) ; une citation déjà là ne se rejuge pas.
- `bmad.approbation` : une spec que le workflow de BMAD fait approuver par
  l'humain ne quitte pas le brouillon sans son approbation consignée, mot
  pour mot, dans le registre des demandes (`socle decision`), et son
  intention figée ne change plus sans une approbation nouvelle.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from socle import bmad, config, language as langue, memory as memoire, utils as outils
from socle.context import controle
from socle.messages import trad

TITRE_MAX = 100


def reports_entres(mem: memoire.Memoire) -> set[str]:
    """Les empreintes des reports de BMAD déjà entrés au backlog, ouverts ou
    clos."""
    return {e.meta["report"].strip() for e in mem.entrees("B") if e.meta.get("report")}


def reports_a_entrer(projet: config.Projet, mem: memoire.Memoire, rev: str | None = None) -> list[bmad.Report]:
    if not bmad.present(projet.racine, rev):
        return []
    texte = outils.lire_a(projet.racine, rev, bmad.fichier_des_reports(projet.racine, rev))
    if not texte:
        return []
    entres = reports_entres(mem)
    vus, res = set(), []
    for r in bmad.reports(texte):
        if r.empreinte not in entres and r.empreinte not in vus:
            vus.add(r.empreinte)
            res.append(r)
    return res


def _titre(resume: str) -> str:
    resume = " ".join(resume.split()).rstrip(".")
    if len(resume) <= TITRE_MAX:
        return resume
    coupe = resume[:TITRE_MAX].rsplit(" ", 1)[0]
    return coupe + " …"


def importer(projet: config.Projet) -> list[tuple[str, str]]:
    """Fait entrer au backlog chaque report de BMAD qui n'y est pas : un sujet
    ouvert par report, qui cite sa source sans recopier la spec. Rend les
    identifiants et les chemins posés."""
    from socle import identifiers as identifiants, private as zone_privee

    racine = projet.racine
    mem = memoire.Memoire.charger(racine)
    a_entrer = reports_a_entrer(projet, mem)
    if not a_entrer:
        return []
    ch = projet.chemins
    lg = langue.du_projet(projet)
    prive = "backlog" in zone_privee.couches_privees(projet)
    if prive:
        acces = zone_privee.acces(projet, mem.illisibles)
        if not acces.disponible:
            raise RuntimeError(trad("refus : mémoire privée indisponible ({raison}) ; une entrée privée ne "
                                    "s'écrit pas à l'aveugle", raison=acces.raison))
    zone = "privee" if prive else "publique"
    dossier = racine / (ch.dans_prive(ch.backlog) if prive else ch.backlog)
    source = bmad.fichier_des_reports(racine)
    jour = date.today().isoformat()
    res = []
    for r in a_entrer:
        ident = mem.prochain_id("B", prive=prive, date=jour, pris_ailleurs=identifiants.pris_ailleurs(racine, "B"))
        titre = _titre(r.resume) or r.empreinte
        lu = memoire.empreinte_index(mem, "backlog")
        meta = langue.meta(lg, "B", statut="ouvert", origine=langue.ref_fichier(source, lg), report=r.empreinte,
                           lu=f"backlog@{lu}")
        corps = langue.mot(langue.TEXTES, "report-bmad", lg).format(source=r.source or "?", resume=r.resume)
        if r.preuve:
            corps += "\n\n" + r.preuve
        chemin = dossier / f"{ident}-{memoire.nom_de_fichier(titre)}.md"
        outils.ecrire(chemin, f"{langue.entete_fichier('backlog', zone, lg)}\n# {ident} — {titre}\n\n{meta}\n\n"
                              f"{corps}\n")
        res.append((ident, chemin.relative_to(racine).as_posix()))
        mem = memoire.Memoire.charger(racine)
    return res


@controle("bmad.reports", etages=("agent", "git", "ci"))
def reports(ctx, r):
    """Un travail que BMAD reporte entre au backlog du socle (ADR-0032) : une
    seule liste des trouvailles, que le socle suit et clôt."""
    if not bmad.present(ctx.racine, ctx.tete):
        return
    for rep in reports_a_entrer(ctx.projet, ctx.memoire, ctx.tete):
        r.erreur("bmad.reports",
                 trad("travail reporté par BMAD, absent du backlog : « {resume} » — le faire entrer : `python3 "
                      ".socle/socle bmad-import`", resume=_titre(rep.resume)),
                 bmad.fichier_des_reports(ctx.racine, ctx.tete))


@controle("bmad.approbation", etages=("agent", "git", "ci"))
def approbation(ctx, r):
    """Une spec de BMAD approuvée l'est par l'humain, consigné mot pour mot
    (ADR-0032), et son intention figée ne change plus sans lui."""
    if not bmad.present(ctx.racine, ctx.tete):
        return
    decisions = [d for d in ctx.demandes if d.validee and d.sujet]
    for s in bmad.specs(ctx.racine, ctx.fichiers, ctx.tete):
        if not s.approuvee:
            continue
        siennes = [d for d in decisions if d.sujet[0] == s.chemin]
        if not siennes:
            r.erreur("bmad.approbation",
                     trad("spec « {statut} » sans l'approbation de l'humain consignée : la consigner, mot pour mot, "
                          "dès qu'il l'a donnée — `python3 .socle/socle decision \"<la question posée>\" valider "
                          "--about {chemin} --relayed --by <nom> --quote-file <texte exact>`",
                          statut=s.statut, chemin=s.chemin), s.chemin)
        elif not any(d.sujet[1] == s.empreinte_intention for d in siennes):
            r.erreur("bmad.approbation",
                     trad("intention figée changée après son approbation ({ids}) : seul l'humain la change — lui "
                          "faire approuver la nouvelle, et la consigner", ids=", ".join(d.id for d in siennes)),
                     s.chemin)


@controle("bmad.lectures", etages=("agent", "git", "ci"))
def lectures(ctx, r):
    """Une décision d'architecture de BMAD citée avec son empreinte
    (`AD-n@empreinte`) l'est dans sa version actuelle (B-0072)."""
    if not bmad.present(ctx.racine, ctx.tete):
        return
    empreintes: dict[str, set[str]] = {}
    for d in bmad.decisions_architecture(ctx.racine, ctx.fichiers, ctx.tete):
        empreintes.setdefault(d.ident, set()).add(d.empreinte)
    for c in ctx.changes:
        if not memoire.est_memoire(c):
            continue
        texte, avant = ctx.lire(c) or "", ctx.lire_base(c) or ""
        for n, ligne in enumerate(texte.splitlines(), 1):
            for m in bmad.CITATION_AD.finditer(ligne):
                if m.group(0) in avant:
                    continue  # déjà là : lue quand elle a été écrite
                ident, h = m.group(1), m.group(2)
                if ident not in empreintes:
                    r.erreur("bmad.lectures", trad("`{citation}` : {ident} ne désigne aucune décision d'architecture "
                                                   "de BMAD", citation=m.group(0), ident=ident), c, n)
                elif h not in empreintes[ident]:
                    r.erreur("bmad.lectures", trad("`{citation}` n'est pas l'empreinte de la version actuelle de "
                                                   "{ident} : la relire, `python3 .socle/socle show {ident}`",
                                                   citation=m.group(0), ident=ident), c, n)

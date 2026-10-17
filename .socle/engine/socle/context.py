"""Le contexte d'un passage de contrôles et le registre des contrôles.

Un contrôle est une fonction `(ctx, rapport)`. Il déclare les étages où il
tourne — `agent` (fin de tour), `git` (commit), `ci` — et s'il a besoin d'une
révision de base (les contrôles « ajout seul », le cliquet, la correspondance
code ↔ doc). Sans base, un tel contrôle le dit au lieu d'être sauté en silence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from socle import config, requests as demandes, memory as memoire, utils as outils
from socle.messages import trad

ETAGES = ("agent", "git", "ci")


@dataclass
class Controle:
    id: str
    fonction: object
    etages: tuple[str, ...]
    base: bool
    lent: bool
    doc: str


REGISTRE: dict[str, Controle] = {}


def resume(doc: str) -> str:
    """La première phrase d'une docstring, sur une ligne : ce que `socle
    checks` montre d'un contrôle, et la clé de sa traduction (ADR-0028)."""
    paragraphe = " ".join(l.strip() for l in (doc or "").strip().split("\n\n")[0].splitlines())
    m = re.match(r".+?[.!?](?=\s|$)", paragraphe)
    return m.group(0) if m else paragraphe


def controle(id_: str, etages=ETAGES, base=False, lent=False):
    def deco(f):
        REGISTRE[id_] = Controle(id_, f, tuple(etages), base, lent, (f.__doc__ or "").strip())
        return f

    return deco


@dataclass
class Contexte:
    projet: config.Projet
    etage: str = "ci"
    base: str | None = None
    tete: str | None = None  # None : l'arbre de travail
    rapide: bool = False
    # Le message du commit en cours d'écriture (hook commit-msg) : il compte
    # comme le dernier commit de la plage, ses trailers avec lui.
    message: str | None = None
    _cache: dict = field(default_factory=dict)

    @property
    def racine(self) -> Path:
        return self.projet.racine

    @cached_property
    def fichiers(self) -> list[str]:
        if self.tete is None:
            # Le clone du dépôt privé (mode compagnon) est ignoré par git,
            # mais c'est de la mémoire : les contrôles la lisent.
            return sorted(set(outils.fichiers_courants(self.racine)) | set(memoire.fichiers_compagnon(self.racine)))
        return outils.fichiers_a(self.racine, self.tete)

    @cached_property
    def format_base(self) -> config.Chemins | None:
        return config.chemins(self.racine, self.base) if self.base else None

    @cached_property
    def migre(self) -> bool:
        """La plage change le format de la mémoire (B-0032) : la base se lit
        alors sous les noms de la tête."""
        return self.format_base is not None and self.format_base.format != self.projet.chemins.format

    @cached_property
    def fichiers_base(self) -> list[str]:
        res = outils.fichiers_a(self.racine, self.base) if self.base else []
        if self.migre:
            res = [config.traduire(c, vers=self.projet.chemins.format) for c in res]
        return res

    def lire(self, chemin: str) -> str | None:
        """Le texte d'un fichier de la tête ; un fichier privé chiffré ici
        n'a pas de texte lisible, les contrôles le prennent pour absent."""
        cle = ("t", chemin)
        if cle not in self._cache:
            texte = outils.lire_a(self.racine, self.tete, chemin)
            if memoire.est_prive(chemin) and not memoire.lisible(texte):
                texte = None
            self._cache[cle] = texte
        return self._cache[cle]

    def lire_base(self, chemin: str) -> str | None:
        if not self.base:
            return None
        cle = ("b", chemin)
        if cle not in self._cache:
            lieu = config.traduire(chemin, vers=self.format_base.format) if self.migre else chemin
            self._cache[cle] = outils.lire_a(self.racine, self.base, lieu)
        return self._cache[cle]

    @cached_property
    def memoire(self) -> memoire.Memoire:
        return memoire.Memoire.charger(self.racine, self.tete)

    @cached_property
    def memoire_base(self) -> memoire.Memoire | None:
        if not self.base:
            return None
        return memoire.Memoire.charger(self.racine, self.base)

    @cached_property
    def demandes(self) -> list[demandes.Demande]:
        return demandes.toutes(self.racine, self.tete)

    @cached_property
    def changes(self) -> list[str]:
        """Ce qui a changé depuis la base (arbre de travail compris si
        `tete` est None)."""
        if not self.base:
            return list(self.fichiers)
        return outils.fichiers_changes(self.racine, self.base, self.tete)

    @cached_property
    def renommes(self) -> dict[str, str]:
        """Les fichiers que la plage renomme, de leur nom à la base à leur nom
        à la tête, tels que git les reconnaît (ADR-0027)."""
        if not self.base:
            return {}
        return outils.renommes(self.racine, self.base, self.tete)

    @cached_property
    def rev_commit(self) -> str:
        """Le commit de la tête. La tête peut être un arbre (l'index, au hook
        pre-commit) : son historique est alors celui de HEAD."""
        if self.tete and outils.rev_existe(self.racine, self.tete):
            return self.tete
        return "HEAD"

    @cached_property
    def commits(self) -> list[dict]:
        res = outils.commits(self.racine, self.base, self.rev_commit) if outils.a_des_commits(self.racine) else []
        if self.message is not None:
            res.append({"sha": "en-cours", "parents": [], "message": self.message})
        return res

    @cached_property
    def validations(self) -> list[demandes.Demande]:
        return demandes.validations_ajoutees(self.racine, self.base, self.tete)

    @cached_property
    def projet_base(self) -> config.Projet | None:
        if not self.base:
            return None
        return config.Projet.charger(self.racine, self.base)

    def textes(self, motifs, exclus=()) -> dict[str, str]:
        res = {}
        for c in outils.filtrer(self.fichiers, motifs, exclus):
            t = self.lire(c)
            if t is not None and "\0" not in t[:4096]:
                res[c] = t
        return res

    def documents(self) -> dict[str, str]:
        """Les documents markdown du projet, hors archives et exclusions."""
        return self.textes(["**/*.md"], self.projet.exclusions_docs())


def selectionner(etage: str, ids: list[str] | None = None, rapide: bool = False) -> list[Controle]:
    res = []
    for c in REGISTRE.values():
        if ids and c.id not in ids:
            continue
        if not ids and etage not in c.etages:
            continue
        if rapide and c.lent and not ids:
            continue
        res.append(c)
    return res


def charger_controles() -> dict[str, Controle]:
    """Tous les contrôles : leurs modules s'enregistrent à l'import. Une
    seule liste, pour que `socle checks` et l'exécution voient les mêmes."""
    from socle import (checks_ratchet as controles_cliquet, checks_docs as controles_docs,
                       checks_memory as controles_memoire, checks_tests as controles_tests, private as prive)  # noqa: F401

    return REGISTRE


def executer(ctx: Contexte, ids: list[str] | None = None):
    from socle.report import Rapport  # import local : pas de cycle
    from socle.report import AVERTISSEMENT, ERREUR

    charger_controles()

    rapport = Rapport()
    for chemin, erreur in ctx.projet.erreurs_config:
        rapport.erreur("config", erreur, chemin)
    # Mode adoption : sur un projet existant, ces contrôles avertissent au lieu
    # d'échouer, le temps de résorber l'existant. Retirer un contrôle de la
    # liste durcit (libre) ; en ajouter un assouplit (cliquet).
    adoption = set(ctx.projet.gf("adoption", "warn_only", defaut=[]) or [])
    for c in selectionner(ctx.etage, ids, ctx.rapide):
        rapport.execute(c.id)
        if c.base and not ctx.base:
            rapport.indisponible(c.id, trad("aucune révision de base : contrôle non exécuté"))
            continue
        debut = len(rapport.constats)
        try:
            c.fonction(ctx, rapport)
        except Exception as e:  # un contrôle en panne échoue, il ne se tait pas
            rapport.erreur(c.id, trad("le contrôle a planté : {erreur}", erreur=f"{type(e).__name__}: {e}"))
        if c.id in adoption:
            for constat in rapport.constats[debut:]:
                if constat.gravite == ERREUR:
                    constat.gravite = AVERTISSEMENT
                    constat.message = "(adoption) " + constat.message
    # En CI, le journal d'un dépôt public est public : un constat de la zone
    # privée n'y montre ni son texte ni son chemin, seulement qu'il existe.
    if ctx.etage == "ci" and ctx.projet.pol("private", "mode"):
        for constat in rapport.constats:
            if constat.chemin and memoire.est_prive(constat.chemin):
                constat.message = trad("constat masqué : zone privée (relancer les contrôles là où elle se lit)")
                constat.chemin, constat.ligne = ctx.projet.chemins.prive + "/…", None
    return rapport

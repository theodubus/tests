"""Ce que le socle lit de BMAD Method (ADR-0032) : planifier appartient à
BMAD, le socle le lit sans le recopier.

- Ses dossiers, dans sa configuration (`_bmad/config.toml`).
- Ses specs : l'en-tête (`status`, `route`) et l'intention figée, que seul
  l'humain change après l'approbation.
- Ses travaux reportés (`deferred-work.md`), que le socle fait entrer dans
  son backlog : un report s'y reconnaît à son empreinte.
- L'état de son sprint (`sprint-status.yaml`).

Des lecteurs petits et tolérants : un format de BMAD qui change rend une
liste vide, pas une panne. La bibliothèque standard n'a pas de YAML ; l'état
du sprint est une table de clés et de statuts, lue ligne à ligne."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from socle import utils as outils

DOSSIER = "_bmad"
CONFIGURATION = "_bmad/config.toml"
IMPLEMENTATION = "_bmad-output/implementation-artifacts"
PLANIFICATION = "_bmad-output/planning-artifacts"
REPORTS = "deferred-work.md"
SPRINT = "sprint-status.yaml"
# Les statuts d'une spec : seul le premier n'engage rien.
BROUILLON = "draft"
FINIE = "done"
# La route d'une spec qui passe par l'approbation de l'humain (le point
# d'arrêt 1 du workflow de construction) ; la route courte ne la demande pas.
ROUTE_APPROUVEE = "dispatch"
FIGEE = re.compile(r"<frozen-after-approval[^>]*>(.*?)</frozen-after-approval>", re.S)


def present(racine: Path, rev: str | None = None) -> bool:
    return outils.lire_a(racine, rev, CONFIGURATION) is not None or (rev is None and (racine / DOSSIER).is_dir())


def dossiers(racine: Path, rev: str | None = None) -> tuple[str, str]:
    """Les dossiers des sorties de planification et d'implémentation, relatifs
    à la racine, tels que la configuration de BMAD les dit."""
    try:
        conf = tomllib.loads(outils.lire_a(racine, rev, CONFIGURATION) or "")
    except tomllib.TOMLDecodeError:
        conf = {}
    bmm = (conf.get("modules") or {}).get("bmm") or {}

    def relatif(valeur, defaut: str) -> str:
        if not isinstance(valeur, str) or not valeur.strip():
            return defaut
        return valeur.replace("{project-root}", "").strip("/") or defaut

    return (relatif(bmm.get("planning_artifacts"), PLANIFICATION),
            relatif(bmm.get("implementation_artifacts"), IMPLEMENTATION))


# --- les specs -------------------------------------------------------------


@dataclass
class Spec:
    chemin: str
    statut: str
    route: str
    intention: str  # le bloc figé, tel qu'écrit ; vide s'il n'y en a pas

    @property
    def empreinte_intention(self) -> str:
        return outils.sha256(re.sub(r"\s+", " ", self.intention).strip())[:8]

    @property
    def approuvee(self) -> bool:
        """Passée par l'approbation de l'humain : sa route le demande, et elle
        a quitté le brouillon."""
        return self.route == ROUTE_APPROUVEE and self.statut not in ("", BROUILLON)


def en_tete(texte: str) -> dict[str, str]:
    """L'en-tête d'un document de BMAD, entre deux lignes `---` : des paires
    `clé: valeur`, les guillemets et les commentaires retirés."""
    lignes = texte.splitlines()
    if not lignes or lignes[0].strip() != "---":
        return {}
    res = {}
    for ligne in lignes[1:]:
        if ligne.strip() == "---":
            return res
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", ligne)
        if m:
            valeur = re.sub(r"\s+#.*$", "", m[2]).strip()
            res[m[1]] = valeur.strip("'\"")
    return {}


def spec(chemin: str, texte: str) -> Spec | None:
    """Une spec de BMAD, reconnue à son en-tête (`status` et `route`)."""
    tete = en_tete(texte)
    if "status" not in tete or "route" not in tete:
        return None
    m = FIGEE.search(texte)
    return Spec(chemin, tete["status"], tete["route"], m.group(1) if m else "")


def specs(racine: Path, fichiers: list[str], rev: str | None = None) -> list[Spec]:
    _, impl = dossiers(racine, rev)
    res = []
    for c in outils.filtrer(fichiers, [impl + "/**/*.md"]):
        texte = outils.lire_a(racine, rev, c)
        s = spec(c, texte) if texte else None
        if s:
            res.append(s)
    return res


# --- les travaux reportés ----------------------------------------------------


@dataclass
class Report:
    source: str
    resume: str
    preuve: str
    texte: str

    @property
    def empreinte(self) -> str:
        return outils.sha256(re.sub(r"\s+", " ", self.texte).strip())[:8]


def reports(texte: str) -> list[Report]:
    """Les entrées de la liste des travaux reportés : `- source_spec: …`,
    puis `summary:` et `evidence:` en retrait."""
    res, courant = [], None
    for ligne in texte.splitlines():
        if re.match(r"^-\s+source_spec\s*:", ligne):
            courant = [ligne]
            res.append(courant)
        elif courant is not None and (ligne.startswith((" ", "\t")) and ligne.strip()):
            courant.append(ligne)
        elif courant is not None and not ligne.strip():
            continue
        else:
            courant = None

    def champ(bloc: list[str], nom: str) -> str:
        for l in bloc:
            m = re.match(rf"^\s*-?\s*{nom}\s*:\s*(.*)$", l)
            if m:
                return m[1].strip().strip("`")
        return ""

    return [Report(champ(b, "source_spec"), champ(b, "summary"), champ(b, "evidence"), "\n".join(b)) for b in res]


def fichier_des_reports(racine: Path, rev: str | None = None) -> str:
    return f"{dossiers(racine, rev)[1]}/{REPORTS}"


# --- l'état du sprint ----------------------------------------------------------


def sprint(texte: str) -> dict[str, str]:
    """`development_status` : chaque epic, story ou rétrospective, et son
    statut."""
    res, dedans = {}, False
    for ligne in texte.splitlines():
        if re.match(r"^development_status\s*:", ligne):
            dedans = True
            continue
        if dedans:
            if ligne and not ligne.startswith((" ", "\t", "#")):
                break
            m = re.match(r"^\s+([\w.-]+)\s*:\s*([\w-]+)", ligne)
            if m:
                res[m[1]] = m[2]
    return res


# --- les décisions d'architecture -----------------------------------------------
#
# Le document d'architecture de BMAD (« architecture spine », reconnu à son
# en-tête `type: architecture-spine`) porte des décisions numérotées, à
# identifiants stables : `### AD-n — <décision>`, puis `Binds`, `Prevents`,
# `Rule`. Le socle les lit comme des décisions (B-0072) : l'état les liste,
# `socle show AD-n` en donne le texte et l'empreinte, et une lecture se
# prouve par `AD-n@empreinte`.

ARCHITECTURE = "architecture-spine"
AD = re.compile(r"^#{2,4}\s*(AD-\d+)\b\s*[—–:-]?\s*(.*)$", re.M)
CITATION_AD = re.compile(r"(?<![\w-])(AD-\d+)@([0-9a-f]{8})\b")


@dataclass
class DecisionArchitecture:
    ident: str  # `AD-n`
    titre: str
    chemin: str
    texte: str

    @property
    def empreinte(self) -> str:
        return outils.sha256(re.sub(r"\s+", " ", self.texte).strip())[:8]

    @property
    def adoptee(self) -> bool:
        """Réglée par l'humain ou par l'existant (`[ADOPTED]`)."""
        return "[ADOPTED]" in self.texte


def decisions_architecture(racine: Path, fichiers: list[str], rev: str | None = None) -> list[DecisionArchitecture]:
    """Les décisions de chaque document d'architecture de BMAD, hors des
    blocs de code ; une décision court jusqu'au titre suivant de son niveau
    ou plus haut."""
    plan, _ = dossiers(racine, rev)
    res = []
    for c in outils.filtrer(fichiers, [plan + "/**/*.md"]):
        texte = outils.lire_a(racine, rev, c) or ""
        if en_tete(texte).get("type") != ARCHITECTURE:
            continue
        lisible = re.sub(r"```.*?```", lambda m: re.sub(r"[^\n]", " ", m.group(0)), texte, flags=re.S)
        titres = list(re.finditer(r"^(#{1,6})\s", lisible, re.M))
        for m in AD.finditer(lisible):
            niveau = len(re.match(r"#+", m.group(0)).group(0))
            fin = next((t.start() for t in titres if t.start() > m.start() and len(t.group(1)) <= niveau), len(texte))
            res.append(DecisionArchitecture(m.group(1), m.group(2).strip(), c, texte[m.start():fin].strip()))
    return res

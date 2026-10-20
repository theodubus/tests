"""Le projet tel que le socle le voit : sa racine et ses quatre fichiers.

- `.socle/engine.lock`     — version et empreinte du moteur (installeur seul) ;
- `.socle/policy.toml`     — politique d'autonomie (humain seul) ;
- `.socle/adapter.toml`    — capacités du langage (validé par l'humain) ;
- `.socle/guardrails.toml` — seuils et couverture des contrôles (cliquet :
  durcir est libre, assouplir exige une demande validée).

Les chemins sont en anglais depuis le format 2 de la mémoire (B-0032) : un
projet au format 1 garde ses noms français (`memoire/`, `politique.toml`…)
jusqu'à sa migration, et le moteur lit les deux. Les clés sont en anglais,
les commentaires et messages en français.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field, replace
from functools import lru_cache
from pathlib import Path

from socle import utils as outils
from socle.messages import trad

DOSSIER = ".socle"
LANCEUR = ".socle/socle"
GIT_HOOKS = ".socle/git-hooks"
TRACE = ".socle/trace/hooks.log"  # ancien emplacement, et hors dépôt git
COMPTEUR_STOP = ".socle/trace/stop-echecs"
INSTRUCTIONS = "AGENTS.md"
# Ce qui ouvre la section du socle dans le fichier d'instructions : AGENTS.md,
# ou CLAUDE.md quand l'installeur l'a gardé comme source (B-0049).
DEBUT_SOCLE = "<!-- socle:debut — section posée par l'installeur, régénérée à chaque mise à jour -->"


@dataclass(frozen=True)
class Chemins:
    """Où vivent les fichiers d'un projet, selon le format de sa mémoire."""

    format: int
    memoire: str
    canonique: str
    actif: str
    backlog: str
    decisions: str
    journal: str
    demandes: str
    archives: str
    prive: str
    termes: str
    reponse: str  # le suffixe d'une réponse humaine, à côté de sa demande
    lock: str
    politique: str
    garde_fous: str
    adaptateur: str
    prive_lock: str
    moteur: str  # le dossier du moteur installé

    @property
    def backlog_en_dossier(self) -> bool:
        """Au format 3, un fichier par sujet dans un dossier (ADR-0025)."""
        return not self.backlog.endswith(".md")

    def dans_prive(self, chemin: str) -> str:
        """Le miroir d'un chemin de la mémoire dans la zone privée."""
        return self.prive + chemin[len(self.memoire):] if chemin.startswith(self.memoire + "/") else chemin


FORMAT_1 = Chemins(1, "memoire", "memoire/canonique.md", "memoire/actif.md", "memoire/backlog.md",
                   "memoire/decisions", "memoire/journal", "memoire/demandes", "memoire/archives", "memoire/prive",
                   "memoire/prive/termes.txt", ".reponse.toml", ".socle/moteur.lock", ".socle/politique.toml",
                   ".socle/garde-fous.toml", ".socle/adaptateur.toml", ".socle/prive.lock", ".socle/moteur")
FORMAT_2 = Chemins(2, "memory", "memory/canonical.md", "memory/active.md", "memory/backlog.md",
                   "memory/decisions", "memory/journal", "memory/requests", "memory/archives", "memory/private",
                   "memory/private/terms.txt", ".answer.toml", ".socle/engine.lock", ".socle/policy.toml",
                   ".socle/guardrails.toml", ".socle/adapter.toml", ".socle/private.lock", ".socle/engine")
# Le format 3 garde les noms du format 2 ; le backlog y devient un dossier,
# un fichier par sujet (ADR-0025).
FORMAT_3 = replace(FORMAT_2, format=3, backlog="memory/backlog")
FORMATS = {1: FORMAT_1, 2: FORMAT_2, 3: FORMAT_3}
# Le format d'une installation neuve (D-0020).
FORMAT_ACTUEL = FORMAT_3

# Le renommage du format 1 au format 2, segment par segment, selon où le
# segment se trouve : sous `.socle/`, ou dans la mémoire.
_SOCLE_1_2 = {"moteur.lock": "engine.lock", "politique.toml": "policy.toml", "garde-fous.toml": "guardrails.toml",
              "adaptateur.toml": "adapter.toml", "prive.lock": "private.lock", "moteur": "engine"}
_MEMOIRE_1_2 = {"canonique.md": "canonical.md", "actif.md": "active.md", "demandes": "requests",
                "prive": "private", "termes.txt": "terms.txt"}


def traduire(chemin: str, vers: int = 2) -> str:
    """Un chemin (ou un motif) d'un format dans l'autre ; inchangé s'il
    n'appartient ni à `.socle/` ni à la mémoire. Les noms changent du
    format 1 au 2 ; le format 3 garde ceux du 2."""
    vers = 2 if vers >= 2 else 1
    socle, mem = _SOCLE_1_2, _MEMOIRE_1_2
    racine_de, racine_vers = ("memoire", "memory") if vers == 2 else ("memory", "memoire")
    suffixe_de, suffixe_vers = (".reponse.toml", ".answer.toml") if vers == 2 else (".answer.toml", ".reponse.toml")
    if vers != 2:
        socle, mem = {v: k for k, v in socle.items()}, {v: k for k, v in mem.items()}
    parts = chemin.split("/")
    if parts[0] == DOSSIER and len(parts) > 1:
        parts[1] = socle.get(parts[1], parts[1])
    elif parts[0] == racine_de:
        parts[0] = racine_vers
        for i in range(1, len(parts)):
            parts[i] = mem.get(parts[i], parts[i])
        if parts[-1].endswith(suffixe_de):
            parts[-1] = parts[-1][: -len(suffixe_de)] + suffixe_vers
    else:
        return chemin
    return "/".join(parts)


def sous_le_format(chemin: str, vers: int) -> str:
    """Le nom qu'un chemin prend au format `vers`, même s'il mêle les deux
    (un lien relatif `../demandes/…` lu depuis `memory/journal/`)."""
    return traduire(traduire(chemin, vers=1 if vers >= 2 else 2), vers=vers)


def chemins(racine: Path, rev: str | None = None) -> Chemins:
    """Le format d'un projet à une révision (l'arbre de travail par défaut) :
    le nom de son verrou le dit ; sans verrou, celui de sa politique, puis de
    son dossier de mémoire ; sans rien, le format actuel."""
    return _chemins(str(racine), rev)


@lru_cache(maxsize=256)
def _chemins(racine: str, rev: str | None) -> Chemins:
    for nom in ("lock", "politique"):
        for f in (FORMAT_2, FORMAT_1):
            if outils.lire_a(Path(racine), rev, getattr(f, nom)) is not None:
                return _forme_du_backlog(Path(racine), rev, f)
    for f in (FORMAT_2, FORMAT_1):
        if (Path(racine) / f.memoire).is_dir() if rev is None else \
                outils.git(Path(racine), "cat-file", "-t", f"{rev}:{f.memoire}", check=False).strip() == "tree":
            return _forme_du_backlog(Path(racine), rev, f)
    return FORMAT_ACTUEL


def _forme_du_backlog(racine: Path, rev: str | None, f: Chemins) -> Chemins:
    """Les noms anglais disent le format 2 ou le 3 ; la forme du backlog les
    départage : un fichier unique au format 2, un dossier au 3. Le verrou
    d'un dépôt dont la mémoire a migré peut retarder (ADR-0025)."""
    if f is FORMAT_2 and outils.lire_a(racine, rev, FORMAT_2.backlog) is None:
        return FORMAT_3
    return f


def oublier_formats():
    """À appeler quand un format change sur disque (installation, migration)."""
    _chemins.cache_clear()

MODE_AMONT = "amont"   # le dépôt qui fabrique le moteur : il le modifie
MODE_PROJET = "projet"  # un projet qui l'utilise : le moteur y est immuable


def chemin_trace(racine: Path) -> Path:
    """La trace des hooks vit dans le répertoire git commun
    (`.git/socle/hooks.log`), que partagent tous les worktrees du dépôt : les
    hooks de l'agent y écrivent depuis le dépôt principal, et le hook git d'un
    commit fait dans un autre worktree y lit la même trace (B-0015). Hors
    dépôt git, l'ancien emplacement."""
    import subprocess

    r = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                       cwd=racine, capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip():
        return Path(r.stdout.strip()) / "socle" / "hooks.log"
    return racine / TRACE


def lire_trace(racine: Path) -> list[str]:
    """Les lignes de la trace, l'ancien emplacement d'abord s'il en reste."""
    lignes = []
    for p in dict.fromkeys([racine / TRACE, chemin_trace(racine)]):
        if p.is_file():
            lignes += [l for l in p.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    return lignes


def lire_toml(texte: str | None) -> dict:
    if not texte:
        return {}
    return tomllib.loads(texte)


def charger_toml(racine: Path, chemin: str, rev: str | None = None) -> dict:
    return lire_toml(outils.lire_a(racine, rev, chemin))


@dataclass
class Projet:
    racine: Path
    chemins: Chemins = FORMAT_ACTUEL
    lock: dict = field(default_factory=dict)
    politique: dict = field(default_factory=dict)
    garde_fous: dict = field(default_factory=dict)
    adaptateur: dict = field(default_factory=dict)
    erreurs_config: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def charger(cls, racine: Path | None = None, rev: str | None = None) -> "Projet":
        racine = outils.trouver_racine(racine)
        p = cls(racine=racine, chemins=chemins(racine, rev))
        for attr, chemin in (
            ("lock", p.chemins.lock),
            ("politique", p.chemins.politique),
            ("garde_fous", p.chemins.garde_fous),
            ("adaptateur", p.chemins.adaptateur),
        ):
            try:
                setattr(p, attr, charger_toml(racine, chemin, rev))
            except tomllib.TOMLDecodeError as e:
                p.erreurs_config.append((chemin, trad("TOML illisible : {erreur}", erreur=e)))
        return p

    @property
    def installe(self) -> bool:
        return bool(self.lock)

    @property
    def mode(self) -> str:
        return self.lock.get("mode", MODE_PROJET)

    @property
    def dossier_moteur(self) -> str:
        """Le répertoire qui contient le paquet `socle`. Un lien vers un autre
        dossier du projet se lit à sa cible : c'est elle que les contrôles
        voient dans l'arbre (ADR-0027)."""
        dossier = self.lock.get("engine_dir", self.chemins.moteur)
        lien = self.racine / dossier
        if lien.is_symlink():
            try:
                return lien.resolve().relative_to(self.racine.resolve()).as_posix()
            except ValueError:
                pass
        return dossier

    # --- garde-fous -----------------------------------------------------

    def budget_octets(self, chemin: str) -> int | None:
        """Le plafond de taille, en octets, que les garde-fous donnent à ce
        chemin ; `None` sans plafond."""
        from socle import utils as outils

        for motif, b in (self.gf("budgets", defaut={}) or {}).items():
            if outils.correspond(chemin, [motif]) and "max_bytes" in b:
                return int(b["max_bytes"])
        return None

    def gf(self, *chemin, defaut=None):
        noeud = self.garde_fous
        for c in chemin:
            if not isinstance(noeud, dict) or c not in noeud:
                return defaut
            noeud = noeud[c]
        return noeud

    def pol(self, *chemin, defaut=None):
        noeud = self.politique
        for c in chemin:
            if not isinstance(noeud, dict) or c not in noeud:
                return defaut
            noeud = noeud[c]
        return noeud

    def chemins_code(self) -> list[str]:
        """Ce qui compte comme du code : l'adaptateur le déclare, les
        garde-fous peuvent l'étendre."""
        res = list(self.adaptateur.get("sources", []))
        res += list(self.gf("memory", "code", defaut=[]))
        return res

    def exclusions_docs(self) -> list[str]:
        """Ce qui n'est pas de la documentation du projet : les archives
        (gardées telles quelles) et le moteur (ses gabarits et son format)."""
        return [self.chemins.archives + "/**", self.dossier_moteur.rstrip("/") + "/**"] + list(
            self.gf("references", "exclude", defaut=[])
        )

    def chemins_tiers(self) -> list[str]:
        """Les fichiers d'un outil tiers installé dans le projet (ses skills,
        ses scripts) : aucun contrôle ne les juge (ADR-0031). Un motif qui
        couvrirait un fichier du socle, de la mémoire ou de la politique est
        écarté, et signalé par `erreurs_tiers`."""
        motifs = self.gf("thirdparty", "paths", defaut=[]) or []
        return [m for m in motifs if isinstance(m, str) and not self._couvre_le_socle(m)]

    def erreurs_tiers(self) -> list[str]:
        """Les motifs de chemins tiers qui couvriraient un fichier que le
        socle garde : ils sont ignorés, et la configuration est en erreur."""
        motifs = self.gf("thirdparty", "paths", defaut=[]) or []
        return [m for m in motifs if not isinstance(m, str) or self._couvre_le_socle(m)]

    def _couvre_le_socle(self, motif: str) -> bool:
        ch = self.chemins
        gardes = [DOSSIER + "/x", ch.memoire + "/x", "AGENTS.md", "CLAUDE.md", ".claude/settings.json"]
        gardes += [re.sub(r"\*+", "x", m) for m in self.pol("protected", "paths", defaut=[]) or []]
        return any(outils.correspond(g, [motif]) for g in gardes)

    def hors_tiers(self, chemins):
        """Les chemins donnés, sans ceux d'un outil tiers."""
        tiers = self.chemins_tiers()
        return [c for c in chemins if not outils.correspond(c, tiers)] if tiers else list(chemins)

    def chemins_proteges(self) -> list[str]:
        res = list(self.pol("protected", "paths", defaut=[]))
        # La zone privée suit les règles de la zone publique : une réponse
        # humaine privée est protégée comme une réponse publique.
        ch = self.chemins
        res += [ch.dans_prive(m) for m in res if m.startswith(ch.memoire + "/") and not m.startswith(ch.prive + "/")]
        if self.mode == MODE_AMONT:
            # Dans le dépôt amont, le moteur EST la source : le protéger
            # empêcherait de le fabriquer.
            res = [m for m in res if not m.startswith(ch.moteur + "/")]
        return res

    def maximum_tentatives(self) -> int:
        return int(self.pol("max_attempts", defaut=3))

"""Le contrat des demandes de décision humaine.

Une demande en file est lue quand le contexte est perdu : elle doit se suffire
à elle-même. Le lint vérifie ce qu'un script peut vérifier — les huit champs,
et qu'aucun identifiant interne n'y paraisse sans description. La qualité de
l'explication, elle, ne se contrôle pas : la réponse `contexte-insuffisant`
renvoie la demande à l'agent, et ce renvoi reste consigné dans la réponse.

Une réponse vit à côté de la demande, dans `<demande>.answer.toml`
(`<demande>.reponse.toml` au format 1 de la mémoire), et
seul l'humain l'écrit (`socle repondre`). Elle porte l'empreinte du texte
exact auquel l'humain a répondu : la demande est gelée dès qu'elle a une
réponse.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from socle import config, language as langue, memory as memoire, utils as outils
from socle.messages import a_traduire, trad

# Les sections et les réponses, sous leurs clés internes ; elles s'écrivent
# dans la langue de la mémoire du projet (B-0031).
SECTIONS = {k: v["fr"] for k, v in langue.SECTIONS.items()}
REPONSE_POSITIVE = "valider"
RENVOI = "contexte-insuffisant"

# Identifiants internes qui ne disent rien à qui n'a pas le projet en tête :
# ceux de la mémoire, un SHA, un numéro de PR ou d'issue. Le projet en ajoute
# d'autres (`requests.internal_id_patterns`), comme les codes de chantier.
MOTIFS_INTERNES = [
    memoire.ID_RE.pattern,
    r"(?<![\w/.@-])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*\d)[0-9a-f]{7,40}(?![\w-])",  # pas une empreinte `ID@…`
    r"(?<![\w&])#\d+\b",
]
MOTS_DESCRIPTION_MIN = 5
SECTION_MIN = 15
# Une demande lue une semaine plus tard, sans le projet en tête : le contexte
# raconte, il ne résume pas en une ligne (retour de Théo, J-2026-10-10-I).
MOTS_CONTEXTE_MIN = 60
LIEN = re.compile(r"\]\([^)\s]+\)|https?://\S+")
# Un trou du gabarit : `<texte avec des espaces>`, hors commentaire HTML ;
# collé à ses chevrons, pour qu'une comparaison (« < 5 », « a <= b ») n'en
# soit pas un. Le code cité, entre accents graves, est un exemple.
TROU = re.compile(r"<(?!!--)[^\s<>=][^<>\n]*\s[^<>\n]*[^\s<>=-]>")
CODE_CITE = re.compile(r"```.*?```|`[^`\n]*`", re.S)


@dataclass
class Demande:
    chemin: str
    texte: str
    entree: memoire.Entree | None
    sections: dict[str, str] = field(default_factory=dict)
    reponse: dict | None = None
    chemin_reponse: str | None = None
    erreur_reponse: str | None = None

    @property
    def id(self) -> str | None:
        return self.entree.id if self.entree else None

    @property
    def statut(self) -> str:
        if self.reponse is None:
            if self.entree and "retiree" in self.entree.meta:
                return "retirée"
            return "en attente"
        r = str(self.reponse.get("reponse", ""))
        return "renvoyée" if langue.reponse(r) == RENVOI else f"répondue : {r}"

    @property
    def validee(self) -> bool:
        return self.reponse is not None and langue.reponse(str(self.reponse.get("reponse", ""))) == REPONSE_POSITIVE

    def reponses_possibles(self) -> list[str]:
        bloc = self.sections.get("reponses-possibles", "")
        return re.findall(r"^\s*[-*]\s+`([^`]+)`", bloc, flags=re.M)

    def accepte(self, reponse: str) -> bool:
        """Une réponse possible, telle qu'écrite ou dans une autre langue
        (`approve` pour `valider`)."""
        return langue.reponse(reponse) in {langue.reponse(p) for p in self.reponses_possibles()}


def chemin_reponse(chemin_demande: str) -> str:
    return chemin_demande[: -len(".md")] + memoire.chemins_de(chemin_demande).reponse


def decouper_sections(texte: str) -> dict[str, str]:
    res: dict[str, list[str]] = {}
    courante = None
    for _, ligne, code in memoire.lignes_hors_code(texte):
        m = None if code else re.match(r"^##\s+(.*?)\s*#*\s*$", ligne)
        if m and not ligne.startswith("###"):
            courante = langue.section(m[1])
            res.setdefault(courante, [])
            continue
        if courante is not None:
            res[courante].append(ligne)
    return {k: "\n".join(v).strip() for k, v in res.items()}


def charger(racine: Path, rev: str | None, chemin: str, texte: str) -> Demande:
    f = memoire.analyser(chemin, texte)
    entrees = [e for e in f.entrees if e.type == "D"]
    d = Demande(chemin=chemin, texte=texte, entree=entrees[0] if entrees else None)
    d.sections = decouper_sections(texte)
    cr = chemin_reponse(chemin)
    brut = outils.lire_a(racine, rev, cr)
    if brut is not None:
        d.chemin_reponse = cr
        try:
            d.reponse = tomllib.loads(brut)
        except tomllib.TOMLDecodeError as e:
            d.reponse = {}
            d.erreur_reponse = trad("réponse illisible : {erreur}", erreur=e)
    return d


def toutes(racine: Path, rev: str | None = None) -> list[Demande]:
    """Les demandes, privées comprises quand elles se lisent : celles du clone
    du dépôt privé, ou déchiffrées ; une demande privée chiffrée ici n'est
    pas lue."""
    if rev is None:
        chemins = set(outils.fichiers_courants(racine)) | set(memoire.fichiers_compagnon(racine))
    else:
        chemins = outils.fichiers_a(racine, rev)
    res = []
    for c in sorted(chemins):
        if memoire.couche_attendue(c) == "demandes":
            texte = outils.lire_a(racine, rev, c)
            if texte is not None and not (memoire.est_prive(c) and not memoire.lisible(texte)):
                res.append(charger(racine, rev, c, texte))
    return res


def motifs_internes(projet: config.Projet) -> list[re.Pattern]:
    supp = projet.gf("requests", "internal_id_patterns", defaut=[])
    return [re.compile(m) for m in MOTIFS_INTERNES + list(supp)]


def identifiants_cites(texte: str, motifs: list[re.Pattern]) -> set[str]:
    res = set()
    for _, ligne, code in memoire.lignes_hors_code(texte):
        if code:
            continue
        for m in motifs:
            for x in m.finditer(ligne):
                res.add(x.group(0))
    return res


def linter(d: Demande, projet: config.Projet) -> list[str]:
    """Les manquements au contrat, en clair. Vide : la demande est conforme."""
    fautes = []
    f = memoire.analyser(d.chemin, d.texte)
    if f.couche != "demandes":
        fautes.append(trad("en-tête `<!-- socle: couche=demandes zone=… -->` absent ou faux"))
    if d.entree is None:
        fautes.append(trad("pas de titre `# D-NNNN — <décision en une phrase>`"))
        return fautes
    if len(d.entree.titre) < 10:
        fautes.append(trad("le titre doit énoncer la décision demandée en une phrase"))
    nom = Path(d.chemin).name
    if not nom.startswith(d.entree.id):
        fautes.append(trad("le nom du fichier doit commencer par {id}", id=d.entree.id))

    for k, titre in SECTIONS.items():
        contenu = d.sections.get(k)
        if contenu is None:
            fautes.append(trad("section « {titre} » absente", titre=titre))
        elif len(re.sub(r"\s+", " ", contenu)) < SECTION_MIN:
            fautes.append(trad("section « {titre} » vide ou trop courte", titre=titre))
        elif TROU.search(CODE_CITE.sub(" ", contenu)):
            # Le gabarit porte les mots que le lint cherche : un trou laissé
            # tel quel passerait pour une section remplie.
            trou = TROU.search(CODE_CITE.sub(" ", contenu)).group(0)
            fautes.append(trad("section « {titre} » : texte du gabarit laissé tel quel ({trou}…)",
                               titre=titre, trou=trou[:40]))

    contexte = d.sections.get("contexte", "")
    if contexte and len(re.findall(r"[^\W\d_]{2,}", contexte)) < MOTS_CONTEXTE_MIN:
        fautes.append(trad("« Contexte » trop court : moins de {n} mots ne suffisent pas à "
                           "quelqu'un qui n'a pas ouvert le projet depuis une semaine",
                           n=MOTS_CONTEXTE_MIN))
    regarder = d.sections.get("ou-regarder", "")
    if "ou-regarder" in d.sections and not LIEN.search(regarder):
        fautes.append(trad("« Où regarder » doit donner un lien vers chaque document ou passage à lire, et "
                           "dire ce qu'il faut y vérifier : le permalien de `socle url <chemin>` ; sans "
                           "adresse de dépôt connue, un lien relatif depuis la demande "
                           "(`[calc.py](../../calc.py)`)"))

    norm = {k: outils.cle(v).replace("-", " ") for k, v in d.sections.items()}
    opts = norm.get("options", "")
    for indice, faute in (("effort", a_traduire("« Options » doit dire l'effort de chaque option")),
                          ("risque", a_traduire("« Options » doit dire le risque de chaque option")),
                          ("reversibilite", a_traduire("« Options » doit dire la réversibilité de chaque option"))):
        if "options" in d.sections and not any(x in opts for x in langue.INDICES[indice]):
            fautes.append(trad(faute))
    cons = norm.get("consequences", "")
    if "consequences" in d.sections:
        if not any(x in cons for x in langue.INDICES["si-valide"]):
            fautes.append(trad("« Conséquences » doit dire ce qui se passe si l'humain valide"))
        if not any(x in cons for x in langue.INDICES["si-refuse"]):
            fautes.append(trad("« Conséquences » doit dire ce qui se passe si l'humain refuse"))
        if not any(x in cons for x in langue.INDICES["sans-reponse"]):
            fautes.append(trad("« Conséquences » doit dire ce qui se passe sans réponse"))
    rec = norm.get("recommandation", "")
    if "recommandation" in d.sections and not (any(x in rec for x in langue.INDICES["verifie"])
                                               and any(x in rec for x in langue.INDICES["suppose"])):
        fautes.append(trad("« Recommandation » doit séparer ce qui est vérifié de ce qui est supposé"))

    possibles = d.reponses_possibles()
    if "reponses-possibles" in d.sections:
        if len(possibles) < 2:
            fautes.append(trad("« Réponses possibles » : au moins deux réponses, en liste `- \\`valeur\\` — "
                               "sens`"))
        if RENVOI not in {langue.reponse(x) for x in possibles}:
            fautes.append(trad("« Réponses possibles » doit proposer `{renvoi}`", renvoi=RENVOI))

    # Aucun identifiant interne sans description, dans la même demande.
    decrits = descriptions(d.sections.get("elements-cites", ""), motifs_internes(projet))
    cites = identifiants_cites(d.texte, motifs_internes(projet)) - {d.entree.id}
    for ident in sorted(cites):
        if ident not in decrits:
            fautes.append(
                trad("identifiant `{ident}` cité sans description : le décrire en clair dans « Éléments cités "
                     "» (`- <identifiant> — ce que c'est, en une phrase`)", ident=ident)
            )
    return fautes


def descriptions(bloc: str, motifs: list[re.Pattern]) -> set[str]:
    """Les identifiants décrits : une puce qui les nomme et dit, en au moins
    cinq mots, ce qu'ils sont."""
    res = set()
    for ligne in bloc.splitlines():
        if not re.match(r"^\s*[-*]\s+", ligne):
            continue
        idents = identifiants_cites(ligne, motifs)
        reste = ligne
        for i in idents:
            reste = reste.replace(i, " ")
        mots = re.findall(r"[^\W\d_]{2,}", reste)
        if len(mots) >= MOTS_DESCRIPTION_MIN:
            res |= idents
    return res


def verifier_reponse(d: Demande) -> list[str]:
    if d.reponse is None:
        return []
    fautes = []
    if d.erreur_reponse:
        return [d.erreur_reponse]
    r = d.reponse.get("reponse")
    if not r:
        fautes.append(trad("réponse sans champ `reponse`"))
    elif not d.accepte(str(r)):
        fautes.append(trad("réponse `{reponse}` absente des réponses possibles de la demande", reponse=r))
    if d.reponse.get("canal") == "conversation" and len(str(d.reponse.get("citation", "")).strip()) < 2:
        fautes.append(trad("réponse relayée depuis la conversation sans la citation exacte de l'humain"))
    attendue = d.reponse.get("empreinte", "")
    if attendue != "sha256:" + outils.sha256(d.texte):
        fautes.append(
            trad("la demande a changé après la réponse : la réponse portait sur un autre texte (une demande "
                 "répondue est gelée ; en écrire une nouvelle qui la remplace)")
        )
    return fautes


CANAUX = ("terminal", "conversation")


def ecrire_reponse(racine: Path, d: Demande, reponse: str, texte: str, par: str, date: str,
                   canal: str = "terminal", citation: str = "") -> str:
    """Écrit la réponse humaine. Refuse une réponse hors des réponses possibles.

    Deux canaux (ADR-0006). `terminal` : l'humain lance lui-même
    `socle answer`. `conversation` : l'humain a répondu dans le chat, et
    l'agent consigne sa réponse ; il doit alors en citer le texte exact, qui
    reste dans le fichier, visible à la relecture du diff."""
    if not d.accepte(reponse):
        raise ValueError(
            trad("`{reponse}` n'est pas une réponse possible : {liste}",
                 reponse=reponse, liste=', '.join(d.reponses_possibles()))
        )
    if d.reponse is not None:
        raise ValueError(trad("{id} a déjà une réponse ({reponse})",
                              id=d.id, reponse=d.chemin_reponse))
    if canal not in CANAUX:
        raise ValueError(trad("canal inconnu : {canal}", canal=canal))
    if canal == "conversation" and len(citation.strip()) < 2:
        raise ValueError(trad("une réponse relayée cite le texte exact de l'humain (--quote ou --quote-file)"))
    cr = chemin_reponse(d.chemin)
    entete = (
        trad("# Réponse humaine donnée dans la conversation, consignée par l'agent avec\n"
             "# le texte exact de l'humain (`citation`). Relue avec le diff.\n")
        if canal == "conversation" else
        trad("# Réponse humaine, écrite par l'humain lui-même (`socle answer`).\n")
    )
    contenu = (
        entete
        + trad("# Elle porte sur le texte exact de {demande}, dont l'empreinte suit.\n", demande=Path(d.chemin).name)
        + f"reponse = {_toml_str(reponse)}\n"
        f"texte = {_toml_str(texte)}\n"
        f"par = {_toml_str(par)}\n"
        f"date = {_toml_str(date)}\n"
        f"canal = {_toml_str(canal)}\n"
        + (f"citation = {_toml_str(citation.strip())}\n" if canal == "conversation" else "")
        + f"empreinte = {_toml_str('sha256:' + outils.sha256(d.texte))}\n"
    )
    (racine / cr).write_text(contenu, encoding="utf-8")
    return cr


def _toml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def validations_ajoutees(racine: Path, base: str | None, tete: str | None) -> list[Demande]:
    """Les demandes validées par une réponse AJOUTÉE dans la plage : une vieille
    validation ne couvre pas un assouplissement nouveau. Une demande se
    reconnaît à son identifiant, qui ne change pas quand une migration
    renomme son fichier et celui de sa réponse (relevé de la passe de
    recul, D)."""
    def cle(d: Demande) -> str:
        return d.id or d.chemin_reponse or d.chemin

    deja = {cle(d) for d in toutes(racine, base) if d.reponse is not None} if base else set()
    return [
        d for d in toutes(racine, tete)
        if d.validee and cle(d) not in deja and not verifier_reponse(d)
    ]


def illisible(projet: config.Projet, d: Demande) -> str | None:
    """Pourquoi l'humain n'a pas pu lire la demande telle qu'elle est (B-0022),
    ou `None`. Au banc, un agent a écrit une demande puis y a relayé une phrase
    que l'humain avait dite avant qu'elle existe. Une demande chiffrée ne se
    lit pas sur GitHub : l'agent la donne en entier dans la conversation."""
    from socle import links as liens, private as prive

    if memoire.est_prive(d.chemin) and prive.mode(projet) == "chiffre":
        return None
    url, avertissement = liens.lien(projet, d.chemin)
    if url is None:
        return avertissement
    if memoire.est_prive(d.chemin):
        return None  # le dépôt privé : `lien` a vérifié qu'elle y est poussée
    sha = liens.commit_pousse(projet.racine)
    if outils.lire_a(projet.racine, sha, d.chemin) != (projet.racine / d.chemin).read_text(encoding="utf-8"):
        return trad("la version poussée diffère de la version locale")
    return None

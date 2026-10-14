"""Le contrat `verify` : les capacités de l'adaptateur, puis les contrôles du
socle, un seul code de sortie.

Toutes les étapes s'exécutent même après un échec. Une étape qui échoue
rapporte sa sortie — la fin, pas un extrait choisi : c'est le moment où on en
a besoin, et la tronquer oblige à relancer.
"""

from __future__ import annotations

import os
import re
import subprocess

from socle import config, utils as outils
from socle.messages import trad
from socle.report import Rapport

ORDRE = ("format", "lint", "build", "tests")
LIGNES_SORTIE = 120
# L'empreinte du dernier arbre sur lequel les étapes rapides ont toutes passé.
MARQUE = ".socle/trace/derniere-verification"


def etapes_rapides(projet: config.Projet, rapport: Rapport, flux=None, refaire: bool = False) -> bool:
    """Les étapes rapides de l'adaptateur, sauf si elles ont déjà toutes passé
    sur cet arbre exact (HEAD, diff, fichiers non suivis et leur contenu) : la
    vérification que l'agent lance, la fin de tour et le hook avant push ne
    paient pas trois fois la même compilation (L6, mesuré sur un projet Rust
    à la copie du projet d'échecs). La CI, elle, refait tout. Rend vrai si
    elles ont tourné."""
    racine = projet.racine
    marque = outils.empreinte_arbre(racine) if outils.a_des_commits(racine) else ""
    fichier = racine / MARQUE
    if marque and not refaire and fichier.is_file() and fichier.read_text().strip() == marque:
        if flux:
            print(trad("  … étapes rapides déjà passées sur cet arbre exact : non relancées (`--redo` pour les "
                       "relancer)"), file=flux, flush=True)
        return False
    avant = len(rapport.erreurs())
    executer_etapes(projet, True, rapport, flux)
    if marque and not any(c.controle.startswith("verify.") for c in rapport.erreurs()[avant:]):
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(marque)
    return True


def etapes(projet: config.Projet, rapide: bool) -> list[tuple[str, dict]]:
    caps = projet.adaptateur.get("capabilities", {})
    res = []
    for nom in ORDRE:
        c = caps.get(nom)
        if c is None:
            continue
        res.append((nom, c))
    for extra in projet.adaptateur.get("steps", []) or []:
        res.append((extra.get("name", "étape"), extra))
    if rapide:
        res = [(n, c) for n, c in res if c.get("fast", False) or "command" not in c]
    return res


# Posée pendant les étapes rapides (D-0019) : un test trop long pour une fin
# de tour s'y met de côté, avec sa raison écrite, et la CI, qui lance toutes
# les étapes sans elle, le joue toujours.
RAPIDE = "SOCLE_RAPIDE"


def executer_etapes(projet: config.Projet, rapide: bool, rapport: Rapport, flux=None):
    env = dict(os.environ)
    env.setdefault("LC_ALL", "C.UTF-8")
    if rapide:
        env[RAPIDE] = "1"
    else:
        env.pop(RAPIDE, None)
    for nom, c in etapes(projet, rapide):
        ident = f"verify.{nom}"
        rapport.execute(ident)
        if "command" not in c:
            rapport.indisponible(ident, trad("capacité absente : {absent} — remplacement : {remplacement}",
                                             absent=c.get('absent', '?'), remplacement=c.get('replacement', '?')))
            continue
        if flux:
            print(f"  … {ident} : {c['command']}", file=flux, flush=True)
        try:
            p = subprocess.run(c["command"], shell=True, cwd=projet.racine, capture_output=True,
                               text=True, encoding="utf-8", errors="replace", env=env,
                               timeout=c.get("timeout", 3600))
        except subprocess.TimeoutExpired:
            rapport.erreur(ident, trad("délai dépassé : {commande}", commande=c['command']))
            continue
        if p.returncode != 0:
            sortie = (p.stdout + p.stderr).rstrip()
            queue = "\n        ".join(sortie.splitlines()[-LIGNES_SORTIE:])
            if c.get("no_tests") and re.search(c["no_tests"], sortie):
                # Un projet qui commence n'a pas encore de test : l'outil le
                # dit par un échec, que l'adaptateur reconnaît (B-0026).
                rapport.avertir(ident, trad("aucun test trouvé (`{commande}`) : un projet qui commence n'en a "
                                            "pas encore ; le premier code s'écrit avec son test",
                                            commande=c['command']))
                continue
            rapport.erreur(ident, trad("`{commande}` a rendu {code}\n        {queue}",
                                       commande=c['command'], code=p.returncode, queue=queue))

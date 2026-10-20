# Le socle, côté humain

Le socle fiabilise la mémoire, la documentation et les tests d'un projet
qu'un agent de code entretient. L'agent écrit ; des contrôles automatiques
attrapent ses erreurs pendant son travail, au commit et en CI ; toi, tu ne
tranches que ce qu'aucun contrôle ne peut trancher.

Les commandes se lancent à la racine du projet :
`python3 .socle/socle <commande>`. Ce guide s'affiche par
`python3 .socle/socle help`.

## Ce que tu fais

### 1. Installer, mettre à jour

```sh
PYTHONPATH=<clone du socle>/engine python3 -m socle install --target . --owner @toi
```

L'adaptateur (le langage du projet et ses outils) se déduit du dépôt ;
`--adapter <nom>` le force. Options : `--private compagnon` ou
`--private chiffre` (une mémoire privée ; le mode compagnon est le plus
sûr, le mode chiffré dépend d'un filtre comme git-crypt que le socle ne
pose pas, et c'est le moins éprouvé), `--review lots` ou
`--review chaque-push` (relire ce qui part avant publication),
`--language en` (la mémoire, les gabarits et les messages du moteur en
anglais), `--adoption` (un projet existant
dont des contrôles échouent : ils passent en avertissement, et ne pourront
que durcir).

Si le projet a déjà son propre état au démarrage (un hook `SessionStart`
à lui), l'installeur le signale : chaque session en recevrait deux, qui se
recoupent. Retire le sien de `.claude/settings.json`, ou n'y laisse que ce
qui est propre au projet ; c'est un réglage de l'agent, que toi seul
modifies.

Avec BMAD Method, la méthode de planification que le socle épouse
(ADR-0032), une seule commande installe les deux : `--with-bmad` pose
d'abord BMAD, à la version éprouvée avec le socle et dans la langue du
projet (il faut Node.js 20.12 ou plus récent pour `npx`, et `uv` pour ses
skills), puis le socle, qui déclare ses fichiers tiers et branche ses
workflows sur la mémoire. `--bmad-version <x.y.z>` en choisit une autre.

La commande finit par « Et maintenant » : tes étapes suivantes, dans
l'ordre, chacune avec sa commande. Une mise à jour relance la même commande
depuis le clone à jour du socle.

En mode compagnon, la mémoire privée vit dans un second dépôt, privé. Crée-le
vide sur GitHub, puis :

```sh
python3 .socle/socle private install --repo <adresse du dépôt privé>
```

Elle le clone, y fait le premier commit, écrit le verrou et crée une clé de
déploiement ; elle finit par les deux gestes qui restent sur GitHub (la clé
en clé de déploiement du dépôt privé, deux secrets dans le dépôt public),
avec le lien de chaque page.

Après le premier push, protège la branche par défaut sur GitHub : dans les
réglages du dépôt, « Rules », un ensemble de règles qui exige la CI du
socle (« Socle — verify, contrôles, auto-test ») et la revue des
propriétaires du code avant toute fusion. Sans lui, une CI rouge n'empêche
pas de fusionner. `socle state` dit si la CI est exigée, et te le rappelle
sinon.

### 2. Décrire le projet

```sh
python3 .socle/socle init --brief <document> --repo
```

Le document est archivé tel quel ; `--repo` relève ce que le dépôt
contient déjà (outils, tests, CI). L'agent te pose ensuite quelques
questions de départ, chacune avec son défaut.

### 3. Répondre aux demandes de l'agent

Quand une décision te revient (assouplir un garde-fou, changer la valeur
attendue d'un test, une décision coûteuse à défaire, une action
irréversible), l'agent écrit une demande qui se suffit à elle-même, et t'en
donne le lien. Tu réponds dans la conversation, par une des réponses
possibles écrites à sa fin ; l'agent consigne ta réponse avec ton texte
exact. `contexte-insuffisant` la lui renvoie, et il la réécrit.

Seul dans ton terminal :
`python3 .socle/socle answer D-NNNN <réponse> --text "<ton texte>"`.

Une question posée en séance, pendant que tu es là (approuver une spec de
BMAD, trancher une question ouverte) : tu réponds dans la conversation, et
l'agent consigne aussitôt la question et ta réponse mot pour mot dans le
même registre (`socle decision`).

### 4. Approuver tes propres changements protégés

La politique, les garde-fous, l'adaptateur, les hooks, la CI et le moteur
sont protégés : les changer sans validation fait échouer le commit. Quand
c'est toi qui les changes (une mise à jour du socle, ta politique) :

```sh
python3 .socle/socle approve --text "<raison>"
```

liste les fichiers protégés changés, puis les approuve sur confirmation, en
écrivant une demande validée (D-NNNN) à commiter avec eux. L'agent ne peut
pas lancer cette commande ; il te citera ce numéro à son tour suivant.

### 5. Relire avant publication, si tu l'as choisi

Avec `review` dans la section `[private]` de la politique, rien ne part vers
le dépôt public sans ton accord : l'agent te montre ce qui part, et tu
réponds dans la conversation. Seul dans ton terminal :
`python3 .socle/socle reviewed --by <toi>`.

### 6. Commiter toi-même

Les mêmes contrôles s'appliquent à tes commits. Une fonction publique
ajoutée ou modifiée est nommée par un test, ou dispensée dans le message du
commit, `Dispense-test: f — <raison>` : le hook te prévient au commit, la CI
refuse sans. Un correctif (sujet `fix:`, ou trailer `Corrige: B-NNNN`)
apporte un test qui échoue sur le commit parent.

## Ce que tu lis

- `python3 .socle/socle state` : où en est le projet, calculé à chaque
  fois, jamais recopié : commit, CI, backlog, demandes en attente, et ce qui
  te revient.
- La fin de chaque intervention de l'agent qui a agi : « Pour toi : », ce
  qui te revient, puis « Ensuite : », la suite.
- La mémoire, dans `memory/` : les faits et leur preuve, le chantier actif,
  les décisions, le journal, le backlog, les demandes.

## Ce qui ne dépend que de toi

- La politique d'autonomie, `.socle/policy.toml` : ce que l'agent décide
  seul, et ce qu'il te demande.
- Assouplir un garde-fou, dans `.socle/guardrails.toml` ; durcir est libre,
  pour l'agent aussi.
- Les actions irréversibles ou externes : pousser sur la branche par
  défaut, publier, supprimer à distance, dépenser. Le hook les refuse à
  l'agent ; il les met au backlog avec `pour : humain`, et l'état te les
  liste.

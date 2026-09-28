# CLAUDE.md — prep-a-fight (`paf`)

Point d'entrée pour Claude Code. Langue de travail : français (code, commits et README en anglais). Le contexte perso de l'utilisateur est dans `CLAUDE.local.md` (ignoré par git) : **rien de perso dans les fichiers commités** (pseudos, serveur, guilde, identifiants, vrais codes de report).

## Projet

Outil local et open source (MIT) pour préparer un boss : timelines des meilleurs logs d'une spec (façon Lorrgs), sims sur le vrai combat reconstruit depuis les logs (façon Raidbots), et plan de CD selon les assigns. Vision et briques : **`ROADMAP.md`**. On avance **une brique à la fois**, chacune avec un plan court ; on commence par le Chaman Élémentaire et un seul boss.

| Élément | Rôle | État |
|---|---|---|
| `src/paf/` | paquet Python, commande `paf` | S1 faite : `paf setup`, `paf doctor` |
| `tests/` | pytest ; marqueurs `network` et `simc` exclus par défaut | |
| `Invoke-LocalTopGear.ps1` | prototype PowerShell de Top Gear (doc : `docs/legacy-topgear.md`) | jamais lancé contre le vrai simc ; à porter en R2 puis supprimer |
| `.env` | `WCL_CLIENT_ID` / `WCL_CLIENT_SECRET` | ignoré par git |

## Conventions Python

- Python ≥ 3.11, dépendances minimales (stdlib `urllib` tant que possible ; `py7zr` pour les .7z de simc).
- `ruff check .` et `pytest` doivent passer avant chaque commit ; CI GitHub Actions (ubuntu + windows).
- `.venv` local : `.venv/Scripts/python -m pip install -e .[dev]`.
- simc installé par `paf setup` dans `~/.paf/simc/<version>/` (surcharges : `--simc`, `PAF_SIMC`, `PAF_HOME`). Le serveur des nightlies ne sert qu'en HTTP (certificat invalide en HTTPS).
- Nombres passés à simc : format invariant (`.` décimal). Sorties de runs dans `runs/<horodatage>/`.

## Conventions PowerShell (tant que le .ps1 existe)

Compatibles Windows PowerShell 5.1 ; UTF-8 avec BOM + CRLF ; ASCII uniquement dans le code ; `[System.Collections.Generic.List[object]]::new()` et `.ToArray()` ; nombres en `InvariantCulture`.

## Faits SimC (sources : wiki simc, issues GitHub, code de l'addon)

- SimC est **100 % CPU**. Nightlies : `http://downloads.simulationcraft.org/nightly/?C=M;O=D`, fichiers `simc-<ver>.<build>.<commit>-win64.7z`. Image Docker `simulationcraftorg/simc`.
- Les options passées **après** le fichier d'entrée écrasent celles du fichier.
- **Profilesets** (CLI seulement) : `profileset."Nom"+=option`, noms uniques sans `.`, plusieurs lignes par profileset. `profileset_work_threads=N`. Pas d'`armory=` avec des profilesets. Enemies définis **après** le profil joueur.
- **JSON (`json2=`)** : `sim.players[0].collected_data.dps.mean` / `.mean_std_dev`, `sim.profilesets.results[].{name,mean,mean_error,mean_stddev,median,iterations}`. Lecture défensive.
- **Raid events** : `adds,count=,first=,cooldown=,duration=,distance=` (`duration` = durée de vie) ; `movement,first=,cooldown=,distance=` ; `vulnerable,duration=,timestamps=` (bonus de dégâts subis, pas une phase) ; `invulnerable` ; `absorb` (branche midnight).
- Reproduire un log : `fixed_time=1`, `vary_combat_length=0`, `max_time=<durée du kill>` (à vérifier en S3).
- **DungeonRoute** : `fight_style=DungeonRoute`, pulls via `raid_events+=/pull,pull=01,…,enemies="nom":PV|…`, `BOSS_` = boss. Export depuis Method Dungeon Tools. DungeonSlice = caricature, à éviter.
- **Export addon `/simc`** : équipé = `slot=,id=…` ; `### Gear from Bags` (par item `#`, `# Nom (ilvl)`, `# upgrade_levels=…`, `# slot=,id=…`) ; `### Weekly Reward Choices … ### End of Weekly Reward Choices` ; `### Linked gear`. `shoulder`/`wrist` au singulier. 1H sans off-hand équipée = lignes d'armes fausses.
- À **vérifier** (S3) : `external_buffs.power_infusion=`, `bloodlust_percent=` / `bloodlust_time=`, override d'une sous-liste d'APL dans un profileset, `save=` pour dumper l'APL par défaut.

## Warcraft Logs (S2)

- API v2 GraphQL `https://www.warcraftlogs.com/api/v2/client`, OAuth2 client credentials (`https://www.warcraftlogs.com/oauth/token`, basic auth id:secret) — testé OK.
- Rankings : `worldData.encounter(id).characterRankings(className, specName, difficulty, metric)` (JSON scalaire non typé, parse défensif ; `page`, `partition`, `serverRegion`).
- Report : `fights{ id startTime endTime encounterID kill phaseTransitions enemyNPCs friendlyPlayers }`, `masterData{ actors abilities }`, `events(... ){ data nextPageTimestamp }`. Filtrer côté serveur (`filterExpression`, `abilityID`) ; surveiller `rateLimitData`.
- Identifier lust / PI / CD par table d'IDs versionnée (nom en secours : les noms dépendent de la langue du log).
- Fixtures de test synthétiques ou pseudonymisées ; cache des réponses dans `.cache/` (ignoré), sans le token.

## Références

- Raidbots : fournit le « SimC Input » brut de chaque run.
- pybots (github.com/scatari69/pybots) : clone de Raidbots, catalogue via wago.tools ; exclut les armes (segfault de leur nightly sur profilesets d'armes).
- QE Live (github.com/Voulk/QuestionablyEpic) : tout dans le navigateur, moteurs importables headless.
- Lorrgs : inspiration pour les timelines.

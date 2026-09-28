# CLAUDE.md — prep-a-fight (`paf`)

Point d'entrée pour Claude Code. Langue de travail : français (code, commits et README en anglais). Le contexte perso de l'utilisateur est dans `CLAUDE.local.md` (ignoré par git) : **rien de perso dans les fichiers commités** (pseudos, serveur, guilde, identifiants, vrais codes de report).

## Projet

Outil local et open source (MIT) pour préparer un boss : timelines des meilleurs logs d'une spec (façon Lorrgs), sims sur le vrai combat reconstruit depuis les logs (façon Raidbots), et plan de CD selon les assigns. Vision et briques : **`ROADMAP.md`**. On avance **une brique à la fois**, chacune avec un plan court ; on commence par le Chaman Élémentaire et un seul boss.

| Élément | Rôle | État |
|---|---|---|
| `src/paf/` | paquet Python, commande `paf` | S1 + R1 : `paf setup`, `paf doctor`, `paf profile` |
| `tests/` | pytest ; marqueurs `network` et `simc` exclus par défaut | |
| `.env` | `WCL_CLIENT_ID` / `WCL_CLIENT_SECRET` | ignoré par git |

Le prototype PowerShell (`Invoke-LocalTopGear.ps1`, Top Gear 3 passes) a été retiré ; il reste dans le premier commit (`git show 243c53f:Invoke-LocalTopGear.ps1`) comme référence pour R2. Le profil courant de l'utilisateur est dans `~/.paf/profiles/current.simc`.

## Conventions Python

- Python ≥ 3.11, dépendances minimales (stdlib `urllib` tant que possible ; `py7zr` pour les .7z de simc).
- `ruff check .` et `pytest` doivent passer avant chaque commit ; CI GitHub Actions (ubuntu + windows).
- `.venv` local : `.venv/Scripts/python -m pip install -e .[dev]`.
- simc installé par `paf setup` dans `~/.paf/simc/<version>/` (surcharges : `--simc`, `PAF_SIMC`, `PAF_HOME`). Le serveur des nightlies ne sert qu'en HTTP (certificat invalide en HTTPS).
- Nombres passés à simc : format invariant (`.` décimal). Sorties de runs dans `runs/<horodatage>/`.

## Faits SimC (sources : wiki simc, issues GitHub, code de l'addon)

- SimC est **100 % CPU**. Nightlies : `http://downloads.simulationcraft.org/nightly/?C=M;O=D`, fichiers `simc-<ver>.<build>.<commit>-win64.7z`. Image Docker `simulationcraftorg/simc`.
- Les options passées **après** le fichier d'entrée écrasent celles du fichier.
- **Profilesets** (CLI seulement) : `profileset."Nom"+=option`, noms uniques sans `.`, plusieurs lignes par profileset. `profileset_work_threads=N`. Pas d'`armory=` avec des profilesets. Enemies définis **après** le profil joueur.
- **JSON (`json2=`)** : `sim.players[0].collected_data.dps.mean` / `.mean_std_dev`, `sim.profilesets.results[].{name,mean,mean_error,mean_stddev,median,iterations}`. Lecture défensive.
- **Raid events** : `adds,count=,first=,cooldown=,duration=,distance=` (`duration` = durée de vie) ; `movement,first=,cooldown=,distance=` ; `vulnerable,duration=,timestamps=` (bonus de dégâts subis, pas une phase) ; `invulnerable` ; `absorb` (branche midnight).
- **DungeonRoute** : `fight_style=DungeonRoute`, pulls via `raid_events+=/pull,pull=01,…,enemies="nom":PV|…`, `BOSS_` = boss. Export depuis Method Dungeon Tools. DungeonSlice = caricature, à éviter.
- **Export addon `/simc`** : équipé = `slot=,id=…` ; `### Gear from Bags` (par item `#`, `# Nom (ilvl)`, `# upgrade_levels=…`, `# slot=,id=…`) ; `### Weekly Reward Choices … ### End of Weekly Reward Choices` ; `### Linked gear`. `shoulder`/`wrist` au singulier. 1H sans off-hand équipée = lignes d'armes fausses.

### Vérifié sur simc 1210-01 (détails : `docs/research/simc-experiments.md`)

- **`fight_style=Patchwerk` efface silencieusement les `raid_events`** : ne pas mettre de fight_style dans un combat reconstruit.
- Adds : **impossible de les tuer par les dégâts** (`health=` ignoré) → durée de vie = `duration=`, tirée des logs. Une ligne par vague : `first=X,cooldown=9999` (`last=` est exclusif) ou `timestamps=30:90:150`.
- `invulnerable,first=,duration=,cooldown=9999` OK. `bloodlust_time=60` (négatif = depuis la fin) ; `override.bloodlust=0` pour retirer. `external_buffs.power_infusion=10/130/250` (séparateur `/` obligatoire).
- JSON : `collected_data.prioritydps` (dégâts boss seul, existe seulement avec adds). Pas de détail par cible. `profileset_metric=dps,prioritydps` → `results[].additional_metrics[]` (libellé « Damage per Second to Priority Target/Boss »). Ne pas utiliser `profileset_output_data=all`.
- Talents : `talents=<string>` et `class_talents=/spec_talents=/hero_talents=nom_snake:rang` (appliqués par-dessus), aussi en profileset ; `save_talents=` pour récupérer la chaîne.
- APL Élém par défaut : listes `precombat`, défaut, `aoe`, `single_target` (pas de `cds`). Un profileset peut redéfinir une liste entière (`+=actions.single_target=...` puis `+=actions.single_target+=/...`) : vérifié.
- **Piège** : un export `/simc` n'a pas d'APL ; simc génère alors l'APL par défaut et **ignore** les `actions.x=` d'un profileset. Toujours injecter l'APL complète (`save_actions=` puis `paf.cdplan.apl_lines`) dans le profil de base avant de surcharger des listes.
- Les options de sim (lust, PI, raid_events) marchent **par profileset** → variantes de combat en un seul run.
- Perf : baseline 340 s à target_error 0.2 ≈ 0,4 s ; +10 profilesets ≈ 2,7 s avec `profileset_work_threads=4`.
- Git Bash réécrit `raid_events=/…` en chemin : `MSYS_NO_PATHCONV=1` ou passer par un fichier.

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

### Mesures live (S2, 2026-09-28)

- Client : `src/paf/wcl.py` (`WCLClient.query(q, vars, cache_ttl)`, `.events(...)` paginé, `.rate_limit()`). Quota : 3600 points/h.
- Zones Midnight : raid **The Venomous Abyss = zone 53** (10 boss, dont Ula'tek) ; M+ S2 = zone 55. Mythique = `difficulty:5`.
- `characterRankings` Élém mythique Ula'tek : seulement 9 classés → prévoir heroic (`difficulty:4`) en repli.
- Tous les events amis d'un kill de 10 min = ~590k events, ~60 pages, 190 s, ~70 points, 105 Mo de cache. **Toujours filtrer** (`sourceID` du joueur, `dataType: Casts/Buffs`, `abilityID`, `filterExpression`) dans les briques suivantes.
- **Positions** : `events(..., sourceID=<joueur>, includeResources:true)` (tous dataTypes). Chaque event porte `x`, `y`, `facing`, `mapID`, `hitPoints` de l'unité désignée par `resourceActor` (1 = source, 2 = cible). Sur les events dont le joueur est la source : ~530 positions/min, écart médian 0,07 s, max 0,7 s (quasi continu, comme le replay WCL), ~1 900 events/min. Les events où il est la cible (soins/absorbs reçus) sont très nombreux et apportent peu de positions : à éviter. Les events de dégâts portent la position de la **cible** (utile pour placer le boss).
- **Coûts mesurés (Ula'tek HM)** : `fightRankings(difficulty, metric:execution)` = 50 kills/page (compo, guilde, durée, `hasMorePages`), ~2 points. Par combat, `table(dataType:DamageDone, viewBy:Target)` + `playerDetails(includeCombatantInfo:true)` (talentTree, gear, stats de chaque joueur) = ~5 points. 200 kills ≈ 1 000 points.

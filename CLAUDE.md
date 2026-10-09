# CLAUDE.md — prep-a-fight (`paf`)

Point d'entrée pour Claude Code. Langue de travail : français (code, commits et README en anglais). Le contexte perso de l'utilisateur est dans `CLAUDE.local.md` (ignoré par git) : **rien de perso dans les fichiers commités** (pseudos, serveur, guilde, identifiants, vrais codes de report).

## Projet

Outil local et open source (MIT) pour préparer un boss : timelines des meilleurs logs d'une spec (façon Lorrgs), sims sur le vrai combat reconstruit depuis les logs (façon Raidbots), et plan de CD selon les assigns. Vision et briques : **`ROADMAP.md`**. On avance **une brique à la fois**, chacune avec un plan court ; on commence par le Chaman Élémentaire et un seul boss.

| Élément | Rôle | État |
|---|---|---|
| `src/paf/` | paquet Python, commande `paf` | v0.3+ : corpus, timelines, template, validate, topgear, talents, droptimizer, mechanics, assigns, optimize, prep, serve (voir README) |
| `tests/` | pytest ; marqueurs `network` et `simc` exclus par défaut | |
| `.env` | `WCL_CLIENT_ID` / `WCL_CLIENT_SECRET` | ignoré par git |

Le prototype PowerShell (`Invoke-LocalTopGear.ps1`, Top Gear 3 passes) a été retiré ; il reste dans le premier commit (`git show 243c53f:Invoke-LocalTopGear.ps1`) comme référence pour R2. Le profil courant de l'utilisateur est dans `~/.paf/profiles/current.simc`.

## Conventions Python

- Python ≥ 3.11, dépendances minimales (stdlib `urllib` tant que possible ; `py7zr` pour les .7z de simc).
- `ruff check .` et `pytest` doivent passer avant chaque commit ; CI GitHub Actions (ubuntu + windows).
- **Releases : uniquement `python tools/release.py X.Y.Z --message <fichier> --notes "..."`** (checks, bump sans BOM, commit, tag, push, publication quand l'installeur est construit ; s'arrête à la première erreur, `--dry-run` pour les checks seuls ; si le build échoue pour une erreur réseau : `gh run rerun <id> --failed` puis `python tools/release.py X.Y.Z --resume --notes "..."`, jamais de publication à la main). Jamais de chaîne bash commit/tag/push à la main, jamais de `git checkout -- .` à l'aveugle (le 2026-10-07 un heredoc a coupé une chaîne `&&` : modifs effacées et tag poussé sur le mauvais commit). La mise à jour intégrée ne prend que `prep-a-fight-setup-<version>.exe`.
- UI : produit et identité visuelle dans `PRODUCT.md` et `DESIGN.md` (plugin impeccable). Tout le CSS vit dans `src/paf/styles/*.css`, lu par `theme.style(nom)` ; aucun bloc de style dans les modules (testé).
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
- `invulnerable,first=,duration=,cooldown=9999` OK, mais **ajouter `retarget=1`** : sinon le joueur continue de taper le boss immunisé jusqu'au prochain spawn d'add (Coiled Altar : ~25 s à 0 DPS). **Mais** avec `retarget=1`, si un add est encore en vie quand l'invulnérabilité se termine, le joueur ne revient **jamais** sur le boss (Nek'zali M : 0 DPS jusqu'à la fin, validation 0,64 → 0,91 une fois corrigé) : `Fight._spawns` fait mourir ces adds 1 s avant et les fait réapparaître après. `bloodlust_time=60` (négatif = depuis la fin) ; `override.bloodlust=0` pour retirer. `external_buffs.power_infusion=10/130/250` (séparateur `/` obligatoire).
- JSON : `collected_data.prioritydps` (dégâts boss seul, existe seulement avec adds). Pas de détail par cible. `profileset_metric=dps,prioritydps` → `results[].additional_metrics[]` (libellé « Damage per Second to Priority Target/Boss »). Ne pas utiliser `profileset_output_data=all`.
- Talents : `talents=<string>` et `class_talents=/spec_talents=/hero_talents=nom_snake:rang` (appliqués par-dessus), aussi en profileset ; `save_talents=` pour récupérer la chaîne.
- APL Élém par défaut : listes `precombat`, défaut, `aoe`, `single_target` (pas de `cds`). Un profileset peut redéfinir une liste entière (`+=actions.single_target=...` puis `+=actions.single_target+=/...`) : vérifié.
- **Piège** : un export `/simc` n'a pas d'APL ; simc génère alors l'APL par défaut et **ignore** les `actions.x=` d'un profileset. Toujours injecter l'APL complète (`save_actions=` puis `paf.cdplan.apl_lines`) dans le profil de base avant de surcharger des listes.
- Les options de sim (lust, PI, raid_events) marchent **par profileset** → variantes de combat en un seul run.
- Perf : baseline 340 s à target_error 0.2 ≈ 0,4 s ; +10 profilesets ≈ 2,7 s avec `profileset_work_threads=4`.
- Git Bash réécrit `raid_events=/…` en chemin : `MSYS_NO_PATHCONV=1` ou passer par un fichier.
- **Mouvement** : un event `movement` qui démarre pendant un autre le **remplace** (il peut le raccourcir). Toujours fusionner les fenêtres qui se chevauchent (`paf.fight.merged_movement`).
- **Mouvement déduit des trajectoires** : trop pénalisant tel quel (les tops castent en bougeant). `paf validate --calibrate` le met à l'échelle ; sur Ula'tek HM, facteur 0 → 0,97 du DPS réel des tops. Les déplacements perso et les assigns (`personal_movement`) ne sont jamais mis à l'échelle.
- **Calibrage des adds** : jamais au-dessus de ×1 (les nombres viennent des logs) ; l'écart de part boss restant vient de la priorité de cible de SimC.
- `gear_crit_rating=` / `gear_haste_rating=` / … **remplacent** le total du stuff : sert à imposer les vraies stats des tops (les logs n'ont pas les stats des objets craftés).
- **Council** (The Lost Explorers : 3 boss à ~1/3 des dégâts chacun) : `desired_targets=2` **sans** fight_style garde les raid_events et ajoute une 2e cible permanente ; `prioritydps` ne compte alors que la 1re → `paf.simc.parse_json` l'ignore quand `desired_targets>1`. Les tops Élém y font 32 % de Chain Lightning (2 boss touchés par cast dans 97 % des cas) : 1 cible = validation 0,69, 2 cibles = 0,93.
- Trinkets on-use : catégorie partagée 1141, **verrou de 20 s** (données 12.1.0.69933), bien modélisé par simc.

## Prépa : ce que les données permettent (vérifié sur Ula'tek HM)

- Mécaniques : Journal des rencontres (`JournalEncounterSection`, drapeaux `IconFlags` : 1 tank, 2 dps, 4 heal, 64 interruptible, 4096 mythique…) ; `DifficultyMask` 0 ou -1 = toutes difficultés.
- Qui gère quoi : `events(dataType:Interrupts)` et `events(dataType:Debuffs, hostilityType:Friendlies, filterExpression:"type='applydebuff'")` par kill (~2 points). Les debuffs de classe (Forbearance, Stagger…) sont filtrés en gardant les noms du journal ou des sorts lancés par les ennemis.
- Les tops gardent Ascendance et le Vile Vial pour le Heart (57 % des casts sur 10 % du combat), Stormkeeper pour les adds : `paf.optimize.tops_alignment`.

## Environnement

- Cette machine coupe 25 à 45 % des connexions HTTP locales (même avec un serveur stdlib minimal) : les tests web réessaient. À signaler si l'UI paraît instable.
- Le vérificateur du mode auto plante parfois sur Bash : passer par l'outil PowerShell (`.venv\Scripts\...`).

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

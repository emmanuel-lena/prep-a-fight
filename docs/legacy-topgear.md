# Outils PowerShell d'origine (prototype, Windows uniquement)

> Documentation d'origine des scripts PowerShell, conservée telle quelle. Seul `Invoke-LocalTopGear.ps1` est présent dans le dépôt ; il sera remplacé par `paf topgear`.

# Droptimizer local (SimC + PowerShell)

Remplace le Droptimizer Raidbots par un run local : génération des profilesets, lancement de `simc`, classement des gains en % vs ta baseline, EV par source. 100 % CPU (le GPU ne sert à rien), donc sur un 13900K un run de ~30 items à `target_error=0.1` prend quelques minutes.

## Prérequis (une fois)

1. **SimC nightly** : https://www.simulationcraft.org/download.html → dézipper (7-Zip) dans `C:\simc\` par exemple. Re-télécharger après chaque hotfix (les APL / spell data bougent).
2. **Addon SimulationCraft** en jeu → `/simc` → coller l'export dans `eduxi.simc` (à côté du script).
   Le `/simc` doit être fait **avec l'off-hand équipée** si tu joues une 1H, sinon toutes les lignes d'armes sont fausses.
3. PowerShell : si le script refuse de se lancer, une fois : `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (ou `Unblock-File .\Invoke-LocalDroptimizer.ps1`).

## Mode 1 — table de loot (CSV)

```powershell
.\Invoke-LocalDroptimizer.ps1 -BaseProfile .\eduxi.simc -Loot .\loot_eduxi_s2.csv -TargetError 0.1
```

Le CSV (`loot_eduxi_s2.csv` est pré-rempli avec les IDs de la BiS list S2) :

| colonne | rôle |
|---|---|
| `name` | libellé affiché |
| `slot` | `head neck shoulder back chest wrist hands waist legs feet finger trinket main_hand off_hand two_hand` (alias acceptés : `ring`, `1h`, `2h`, `shield`, `staff`, `trinket1`, `finger2`…). `finger`/`trinket` sont testés dans les 2 slots, on garde le meilleur. |
| `id` | item ID Wowhead |
| `bonus_id` | optionnel, ex. `10256/12345`. Prioritaire sur `ilvl`. À copier depuis un **SimC Input** Raidbots ou depuis un lien Wowhead (`?bonus=…`). |
| `ilvl` | optionnel, utilisé via `ilevel=` si pas de `bonus_id`. Par défaut 318 dans le CSV (= Myth 1/6, coffre / Voidcore HM ou +10). |
| `source` | boss / donjon, sert au tableau d'EV par source |
| `skip` | `1` pour ignorer la ligne sans la supprimer |

- `-Ilvl 311` force toute la table (lignes sans `bonus_id`) à un ilvl, comme le sélecteur d'ilvl Raidbots.
- Les enchantements de la pièce équipée dans le même slot sont recopiés sur l'item testé (comme Raidbots).
- Bâton équipé et tu veux tester une dague : `-OffHandLine "off_hand=,id=268262,ilevel=318"` (l'off-hand est ajoutée à chaque profileset 1H). Cas inverse (`off_hand` testée avec un bâton équipé) : `-MainHandLine`.
- Un 2H testé alors que tu joues 1H+OH vide automatiquement l'off-hand dans le profileset.

## Mode 2 — rejouer un SimC Input Raidbots

Sur un résultat Droptimizer Raidbots (gratuit), ouvre « SimC Input », copie tout dans un `.simc`, puis :

```powershell
.\Invoke-LocalDroptimizer.ps1 -RaidbotsInput .\altar_of_fangs.simc -TargetError 0.05
```

Plusieurs fichiers = les profilesets sont fusionnés sous la baseline du premier (ce que Raidbots réserve au premium avec « all dungeons ») :

```powershell
.\Invoke-LocalDroptimizer.ps1 -RaidbotsInput .\altar.simc, .\voidscar.simc, .\kings_rest.simc -NameMap .\loot_eduxi_s2.csv
```

Les noms de profilesets Raidbots sont des IDs encodés ; `-NameMap` (n'importe quel CSV avec `id,name`) ou `-ResolveNames` (tooltip Wowhead, cache local) servent à afficher des noms lisibles. Le nom du fichier sert de « source ».

## Options communes

| option | défaut | |
|---|---|---|
| `-TargetError` | 0.1 | 0.2-0.3 pour un tri rapide, 0.05-0.1 pour départager des items proches |
| `-Iterations` | 1 000 000 | plafond ; avec `-TargetError 0` = nombre exact d'itérations |
| `-Threads` | 0 (= tous) | |
| `-WorkThreads` | 0 (séquentiel) | ex. `4` → 8 profilesets en parallèle sur 32 threads ; à tester, parfois plus rapide sur beaucoup de petits profilesets |
| `-FightStyle` | celui du profil | `Patchwerk`, `DungeonSlice`, `CastingPatchwerk`, `HecticAddCleave`… |
| `-MaxTime` / `-Targets` | ceux du profil | durée (s) / nombre de cibles |
| `-SimcExtra` | | options brutes, ex. `-SimcExtra "optimal_raid=0","report_details=0"` |
| `-SimcPath` | auto (PATH, `C:\simc`, Downloads…) | |
| `-OutDir` | `.\runs\<horodatage>` | |
| `-Top 15` | tout | |
| `-DryRun` | | génère `run.simc` sans lancer simc (pour vérifier / éditer à la main) |
| `-OpenReport` | | ouvre le rapport HTML simc à la fin |

## Sortie

Dans `runs\<horodatage>\` : `results.csv` (classement), `report.html` (rapport simc complet), `report.json`, `run.simc` (rejouable / éditable), `simc.log`, `profilesets_map.json`.

Console : `Delta%` = gain vs baseline, `+/-%` = erreur statistique du profileset. **Un delta inférieur à l'erreur n'est pas significatif** → baisser `-TargetError` pour départager. Vert = gain supérieur à l'erreur.

EV par source = moyenne des gains sur tous les items de la source (pertes comptées 0), même définition que Raidbots.

## Pièges connus

- **Off-hand** : 1H sans off-hand dans le profil = toutes les lignes d'armes 1H sont fausses. Le script prévient, mais c'est l'export `/simc` qu'il faut refaire.
- **Armes via `ilevel=`** : certaines nightlies ont segfault sur des profilesets d'armes avec `ilevel=`. Si `simc` crash sur une ligne d'arme, mets un `bonus_id` (copié d'un SimC Input Raidbots) ou change de nightly.
- Le JSON simc est lu par `ConvertFrom-Json` : sur Windows PowerShell 5.1 c'est lent sur les gros rapports (quelques dizaines de secondes). PowerShell 7 est bien plus rapide.
- 13900K : `simc` à fond = ~250 W en continu. Microcode Intel à jour avant les gros batchs.

---

# Top Gear local multi-profils (`Invoke-LocalTopGear.ps1`)

Répond à « quel est mon meilleur set, boss par boss ? ». Deux passes :

1. **Passe 1** — chaque item du sac / coffre / lien est simmé seul contre ton set équipé, sur chaque profil de combat. On garde les meilleurs par slot (`-KeepArmor 2`, `-KeepJewelry 3`, `-KeepWeapons 3`, `-PruneBelow -2`).
2. **Passe 2** — toutes les combinaisons des items gardés sont simmées sur chaque profil, avec les règles : au moins 4 pièces de tier (`-MinTier`), 1 seul item de coffre par set, anneaux/bijoux distincts, dague+bouclier ou bâton. Plafond `-MaxCombos 1500` (au-delà, les moins bonnes options sont retirées automatiquement).

```powershell
# export /simc avec la case "Bags" cochee (le coffre est inclus s'il est ouvert)
.\Invoke-LocalTopGear.ps1 -BaseProfile .\eduxi.simc -ResolveNames
.\Invoke-LocalTopGear.ps1 -BaseProfile .\eduxi.simc -Fights .\fights.csv -Pass2Error 0.1 -WorkThreads 4
```

## Les profils de combat (`fights.csv`)

| colonne | rôle |
|---|---|
| `name` | libellé |
| `weight` | poids dans le classement global (`0` = ligne désactivée) |
| `fight_style` | `Patchwerk`, `DungeonSlice`, `CastingPatchwerk`, `HecticAddCleave`, `LightMovement`, `HeavyMovement`… |
| `targets` | nombre de cibles (`desired_targets`) — vide pour DungeonSlice |
| `max_time` | durée en secondes |
| `raid_events` | événements SimC séparés par `\|`, ex. `adds,count=4,first=45,cooldown=60,duration=20` ou `movement,first=20,cooldown=30,distance=15` |
| `talents` | string de talents pour ce profil (build AoE, build mono…) — vide = celle de l'export |
| `extra` | options brutes séparées par `\|`, ex. `bloodlust_percent=25\|override.bloodlust=0` |
| `file` | fichier `.simc` dont les lignes sont injectées telles quelles (pour les profils longs : route M+ complète en `DungeonRoute`) |

### M+ réaliste : `DungeonRoute` au lieu de `DungeonSlice`

`DungeonSlice` (le M+ par défaut de SimC / Raidbots) est une caricature : un boss, puis des packs de taille fixe dont les mobs meurent au chrono. `DungeonRoute` simule une vraie route : chaque pull est une liste de mobs avec leurs PV, le pull se termine quand ils sont morts, avec un temps de trajet entre les pulls et des boss taggés `BOSS_`.

Pour l'avoir avec tes routes S2 : Method Dungeon Tools + la WeakAura « SimC Export » de MDT (bouton en haut à droite de MDT, réglage du % de PV que tu fais toi-même, 27 % par défaut) → colle l'export dans un `.simc` et référence-le dans la colonne `file`. `route_exemple.simc` montre le format attendu. Une route par donjon = un profil par donjon, avec son poids.

Le fichier livré active 5 presets (1/2/3 cibles, AoE 5, M+) et contient 3 exemples désactivés (boss à adds, boss à mouvement, build AoE) à copier pour faire un profil par boss. Un « boss » SimC reste une approximation : assez pour trancher mono / cleave / AoE, pas pour reproduire un boss au détail près.

## Ce que ça sort

- **Meilleur set par profil** et **classement global pondéré** (colonnes par profil) avec, pour chaque set, uniquement ce qui change par rapport à l'équipé.
- **Regret** : ce que tu perds sur chaque profil si tu gardes le set global partout → dit s'il vaut le coup de swapper entre deux boss.
- `combos.csv` (tout le classement), `best_sets.simc` (gear complet des meilleurs sets, à coller dans Raidbots ou dans le droptimizer comme nouvelle base), et par profil `pass1_*/` `pass2_*/` (run.simc, report.html, csv).

## Droptimizer re-optimisé : les items que tu n'as pas encore, dans les combinaisons

```powershell
.\Invoke-LocalTopGear.ps1 -BaseProfile .\eduxi.simc -Loot .\loot_eduxi_s2.csv -ResolveNames
```

Avec `-Loot`, une **passe 3** insère chaque item de la table de loot dans tes meilleurs sets (l'équipé + les `-LootBase 10` meilleurs sets globaux et par profil issus de la passe 2), puis re-simme le tout. Pour chaque item tu obtiens :

- **Réel** = meilleur set AVEC l'item − meilleur set SANS (c'est la vraie valeur de l'obtenir, une fois le reste du stuff réarrangé autour) ;
- **Simple** = la valeur droptimizer classique (un seul swap sur le set équipé), pour comparer ;
- le détail par profil, le set complet dans `best_sets.simc` (« Si tu obtiens X ») et l'EV par source.

`-MaxLootItems 2` ajoute les paires d'items de loot (« si j'ai les deux »), avec une section dédiée — beaucoup plus long. `-LootBase 0` insère dans *tous* les sets de la passe 2 (exhaustif, très long). `-Pass3Error` règle la précision de cette passe (défaut = `-Pass2Error`). Les items de loot ne sont jamais retirés par le plafond `-MaxCombos` (il ne concerne que la passe 2).

## Options utiles

| option | défaut | |
|---|---|---|
| `-Pass1Error` / `-Pass2Error` | 0.3 / 0.15 | précision des deux passes |
| `-TwoHandIds 260000` | | IDs des bâtons / 2H du sac (sinon `-ResolveNames` les détecte via Wowhead) |
| `-TierIds` / `-MinTier` | tier Elem S2 / 4 | `-MinTier 0` pour lever la contrainte |
| `-NoVault` | | ignorer les choix du coffre |
| `-SkipPass1` | | tout le sac directement en combinaisons (petits sacs) |
| `-WorkThreads 4` | 0 | profilesets en parallèle, souvent plus rapide sur des centaines de petits sims |
| `-DryRun` | | génère les `run.simc` sans lancer simc |

Astuce : `/simc [lien d'item]` dans le chat ajoute un item que tu n'as pas (section « Linked gear ») → il entre dans les combinaisons.

## Limites

- Type d'arme : le script ne sait pas seul si une arme du sac est 1H ou 2H → `-TwoHandIds` ou `-ResolveNames`. Sans off-hand équipée, l'arme équipée est traitée comme 2H.
- Limite de 2 embellissements non vérifiée ; gemmes prises telles quelles (un item sans gemme reste sans gemme) ; les enchantements de la pièce équipée sont recopiés sur les candidats.
- Temps : passe 1 en quelques minutes ; passe 2 = combos × profils ; passe 3 ≈ items de loot × sets de base × profils. Le script affiche une estimation avant chaque passe. Si c'est trop long : `-Pass2Error 0.2`, `-MaxCombos 500`, `-LootBase 5`, ou moins de profils actifs. Les résultats de chaque profil sont écrits au fur et à mesure (`pass*/results.csv`), donc un plantage tardif ne perd pas tout.

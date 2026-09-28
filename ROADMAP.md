# Roadmap longue durée — prep-a-fight (`paf`)

> Objectif final découpé en briques. On implémente ensuite **une brique à la fois**, chacune avec son petit plan au moment de la faire.

## Vision
**Préparer son boss en 5 minutes au lieu de 2 h de logs.**
Tu choisis ta spec et un boss. L'outil te dit :
- ce que font les meilleurs de ta spec sur ce boss ;
- quel stuff prendre pour ce combat ;
- quel plan de CD suivre compte tenu de tes assigns.

Trois parties, un seul outil local et open source :

| Partie | Inspiration | Question | Moteur |
|---|---|---|---|
| **1. Timelines** | Lorrgs | « Qu'est-ce que font les meilleurs de ma spec sur ce boss ? » | Warcraft Logs |
| **2. Sims** | Raidbots | « Quel stuff, sur *ce* combat ? » | SimC local |
| **3. Prépa** (custom) | — | « Mon plan à moi, pour ce boss, avec mes assigns » | 1 + 2 combinés |

### Partie 1 — Timelines (façon Lorrgs)
- Top N d'une spec sur un boss et une difficulté donnés.
- Timeline des CD de chaque joueur, alignée sur la timeline du boss : phases, casts du boss, adds.
- Vue agrégée : « 80 % des tops gardent Ascendance pour la vague 2 », lust, PI reçus.
- Sortie : page HTML locale, lisible en un coup d'œil.

### Partie 2 — Sims (façon Raidbots, en plus précis)
- Top Gear et Droptimizer en local, sur le CPU de l'utilisateur.
- Différence clé : en plus des Patchwerk/AoE, on simme le **vrai combat**, reconstruit depuis les logs de la partie 1 : durée, vagues d'adds, phases, lust.
- Résultat : meilleur set par boss et regret si on ne change pas de stuff.

### Partie 3 — Prépa (à concevoir ensemble)
Pistes de départ, à trier et à préciser avec Manu :
- plans de CD candidats tirés des tops (partie 1), départagés par SimC sur le vrai combat (partie 2) ;
- mes assigns (liste simple ou note MRT) → mouvements et indisponibilités ajoutés au combat simulé ;
- catalogue des mécaniques (Journal des rencontres via wago.tools) et détection empirique de ce qui est assigné ou raid-wide dans les tops ;
- mes logs comparés aux tops : CD perdus, DPS par phase, mécaniques prises en plus ;
- une **fiche de boss** d'une page : stuff, plan de CD, points d'attention.

### Rendu cible (exemple)

```
Ula'tek (heroic) - Elemental - objective: boss 70% / adds 30%
Fight rebuilt from 20 top logs: 5:40, 3 add waves
  wave 1  1:05  x3 adds, alive ~22 s
  wave 2  2:50  x3 adds, alive ~25 s
  wave 3  4:30  x5 adds, alive ~18 s

Best talent builds on THIS fight        boss dps   add dmg   score
  1. Build A (8 of the top 20)           -0.8%     +14.2%    +3.7%   <- best compromise
  2. Build B (5 of the top 20)           +0.0%      +0.0%     ref
  3. Your current build                  +0.3%      -6.1%    -1.6%

What changes vs your build: take X instead of Y, Z instead of W
Cooldowns: hold Ascendance for wave 2 (2:50): +1.9% vs on cooldown
```

Chaque ligne vient d'une brique : vagues d'adds (T2), combat SimC (R3), objectif boss/adds (R5), talents (R6), plan de CD (Prépa).

## Principes
- Local et gratuit : simc sur le CPU de l'utilisateur, identifiants WCL de l'utilisateur.
- **Petit d'abord** : Chaman Élémentaire, un boss, puis on élargit.
- Chiffré : delta %, erreur statistique, significativité ; « suivi par X % des tops ».
- Honnête : SimC évalue des plans, il ne les invente pas ; un combat reconstruit reste une approximation.
- **Outil d'analyste** : on ne regarde pas 5 logs, on analyse un **corpus** (200+ kills d'un boss), avec des distributions et des cohortes (top 50 vs guildes comparables à l'utilisateur). Le corpus formule les hypothèses (corrélations), SimC les vérifie.
- Python, multi-OS. Rapports HTML locaux d'abord, UI web ensuite. Aucune donnée perso ni aucun pseudo réel dans le dépôt.

## Briques

### Socle
- **S1** ✅ Dépôt : git, pyproject, CI, `paf setup` (téléchargement de simc).
- **S2** ✅ Client WCL : OAuth2, GraphQL, pagination, rate limit, cache.
- **S3** ✅ Moteur SimC : lancement, profilesets, lecture du JSON ; options vérifiées (`save=`, override d'APL, PI externe, lust, durée fixe).

### Partie 1 — Timelines et analyse
- **T1** ✅ **Corpus** d'un boss (`paf corpus "Ula'tek"`) : collecte de N kills (200 par défaut) via `fightRankings` (tout le raid) et `characterRankings` (une spec). Pour chaque combat : compo, durée, guilde, dégâts de chaque joueur **par cible** (boss et chaque type d'add), talents, stuff, ilvl de chaque joueur. Stockage dans une base SQLite locale, collecte reprenable. Choix de la difficulté (`--difficulty lfr|normal|heroic|mythic`), difficulté par défaut réglable (`paf config difficulty heroic`) ; si trop peu de kills, on le signale et on propose la difficulté du dessous. Coût mesuré : ~5 points de quota par combat, soit ~1 000 points pour 200 kills (quota 3 600/h).
- **T1b** ✅ Premières analyses du corpus :
  - part des dégâts sur les adds par spec ;
  - qui est « assigné adds » ;
  - fréquence de chaque talent par spec, et lien avec les dégâts adds/boss ;
  - durée de vie des adds par cohorte.
- **T2** ✅ Extraction par log : casts de CD du joueur, lust, PI, phases, casts du boss, adds, **talents du joueur**, et **trajectoire x/y + orientation** (events dont le joueur est la source : ~1 point toutes les 0,1 s, quelques points de quota par combat).
- **T3** ✅ Page HTML timeline : top N côte à côte + timeline du boss.
- **T4** ✅ Vue agrégée : quand les tops utilisent chaque CD, par phase et par vague.

### Partie 2 — Sims
- **R1** ✅ Parse de l'export `/simc` (équipé, sac, coffre, liens) : `paf profile`, depuis le presse-papier ou un fichier.
- **R2** ✅ Top Gear multi-profils avec regret (logique du prototype PowerShell, retiré ; il reste dans l'historique git).
- **R3** ✅ Log → combat SimC (`fights/<boss>.simc`) à partir de T2, utilisé comme profil par R2.
- **R4** ✅ Droptimizer : tables de loot via wago.tools, EV par source, loot inséré dans les meilleurs sets.
- **R5** ✅ (Top Gear, plans de CD) Objectif d'optimisation au choix : **dégâts boss** (cible prioritaire : métrique `prioritydps` de SimC), **cleave**, **pad** (dégâts totaux, adds compris), ou un mix pondéré. Même sim, classement différent selon ce que la strat demande.
- **R6** ✅ Sim de talents : comparer des builds en profilesets (`talents=`) sur le vrai combat. Candidats : les builds des tops (récupérés dans leurs logs WCL), les builds de l'utilisateur, et des variantes (un talent échangé contre un autre).

### Templates de combat et combat personnalisé
- **F1** ✅ **Template de combat par boss**, construit à partir du corpus (les 100 à 200 premiers logs), par cohorte :
  - timeline moyenne du boss : phases, casts du boss, vagues d'adds (moment, nombre, durée de vie) ;
  - pour chaque spec, **comment elle joue** :
    - fenêtres de mouvement typiques (tirées des trajectoires) ;
    - usage des CD, calé sur les phases et les vagues ;
    - part des dégâts sur les adds.

  Sortie : un fichier de combat lisible et modifiable, et directement simmable.
- **F2** ✅ **Éditeur de combat perso** : partir du template et dire « là je bouge 6 s », « là je soak », « là je garde Ascendance ». Chaque élément peut être **fixe** ou **décalable** (fenêtre au plus tôt / au plus tard, par exemple un déplacement qu'on peut avancer de 5 s).
- **F3** ✅ **Optimiseur** : SimC teste les décalages possibles des éléments décalables et des CD (profilesets : les options de combat varient par profileset, c'est vérifié). Il ressort le meilleur placement, par exemple « bouge 4 s plus tôt et garde Stormkeeper pour après le déplacement : +2,1 % ».

### Assigns et mécaniques (validé avec Manu, 2026-09-28)
- **A1** **Catalogue automatique des mécaniques** par boss : sorts du boss depuis le Journal des rencontres (wago.tools : nom, description, drapeaux tank/heal/dps/interruptible) croisés avec les casts vus dans les logs.
- **A2** **Pré-tri automatique depuis le corpus** : pour chaque mécanique, qui la gère dans les tops. Kicks via les events `interrupt`, soaks/orbes/debuffs via les dégâts et debuffs reçus. Une mécanique prise par 1 à 3 joueurs fixes est **assignée**, prise par tout le raid elle est **raid-wide**. On en tire les specs qui s'en chargent et le coût mesuré (déplacement, temps sans caster, DPS sur la fenêtre).
- **A3** **Assigns joueur** : liste de cases à cocher par boss, pré-remplie selon la spec (« je kick l'add », « je ramène les orbes »). Chaque case devient des fenêtres de déplacement ou d'indisponibilité dans le combat simulé, avec les timings des logs. Dev manuel seulement pour les mécaniques exotiques.
- **A4** **Déroulé idéal** (`paf optimize`, en cours) : règles de CD optimisées par objectif (boss / total / adds) avec les assigns, sortie dans la fiche HTML et en note MRT.

### Partie 3 — Prépa (briques définies ensemble le moment venu)
- **P1** Atelier de conception avec Manu : choisir et ordonner les pistes ci-dessus.
- P2… à définir.
- Principe : **tout doit être personnalisable**. L'utilisateur choisit son objectif (boss / cleave / pad), ses assigns, ses talents candidats, ses plans de CD. L'outil propose des défauts tirés des tops, mais n'impose rien.

### Plus tard
- Autres specs (données par spec sorties du code).
- M+ (DungeonRoute / MDT).
- UI web locale.
- Releases et installation en une commande.

## Jalons
- **v0.1** = S1, S2, T1, T1b, T2, T3 : corpus d'un boss + premières analyses + timelines Élém.
- **v0.2** = S3, R1 → R3, F1 : template de combat par boss + Top Gear sur le vrai combat.
- **v0.3** = T4, R4, R5, R6, F2, F3, P1 : objectif boss / cleave / pad, sim de talents, combat perso + optimiseur de placement.
- **v0.4+** = partie 3 et élargissement.

Fait aussi :
- `paf cdplan` : plans de CD (APL par défaut, tout au CD, garder pour les adds, timings des tops) ;
- `paf calibrate` : calibrage du combat sur la part de dégâts boss réelle. Limite trouvée : SimC garde ses sorts mono-cible sur le boss, donc l'écart résiduel est affiché dans la fiche ;
- `paf prep` : **la fiche de boss d'une page**, qui enchaîne tout.

Prochaines briques : UI web locale (coller `/simc`, choisir un boss, voir la fiche), autres specs (données par spec hors du code), passe « loot dans les meilleurs sets » du Droptimizer, M+.

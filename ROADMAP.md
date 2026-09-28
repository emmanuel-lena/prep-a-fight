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

## Principes
- Local et gratuit : simc sur le CPU de l'utilisateur, identifiants WCL de l'utilisateur.
- **Petit d'abord** : Chaman Élémentaire, un boss, puis on élargit.
- Chiffré : delta %, erreur statistique, significativité ; « suivi par X % des tops ».
- Honnête : SimC évalue des plans, il ne les invente pas ; un combat reconstruit reste une approximation.
- Python, multi-OS. Rapports HTML locaux d'abord, UI web ensuite. Aucune donnée perso ni aucun pseudo réel dans le dépôt.

## Briques

### Socle
- **S1** ✅ Dépôt : git, pyproject, CI, `paf setup` (téléchargement de simc).
- **S2** Client WCL : OAuth2, GraphQL, pagination, rate limit, cache.
- **S3** Moteur SimC : lancement, profilesets, lecture du JSON ; options vérifiées (`save=`, override d'APL, PI externe, lust, durée fixe).

### Partie 1 — Timelines
- **T1** Top N d'une spec sur un boss (`paf top`).
- **T2** Extraction par log : casts de CD du joueur, lust, PI, phases, casts du boss, adds.
- **T3** Page HTML timeline : top N côte à côte + timeline du boss.
- **T4** Vue agrégée : quand les tops utilisent chaque CD, par phase et par vague.

### Partie 2 — Sims
- **R1** ✅ Parse de l'export `/simc` (équipé, sac, coffre, liens) : `paf profile`, depuis le presse-papier ou un fichier.
- **R2** Top Gear multi-profils avec regret (logique du prototype PowerShell, retiré ; il reste dans l'historique git).
- **R3** Log → combat SimC (`fights/<boss>.simc`) à partir de T2, utilisé comme profil par R2.
- **R4** Droptimizer : tables de loot via wago.tools, EV par source, loot inséré dans les meilleurs sets.

### Partie 3 — Prépa (briques définies ensemble le moment venu)
- **P1** Atelier de conception avec Manu : choisir et ordonner les pistes ci-dessus.
- P2… à définir.

### Plus tard
- Autres specs (données par spec sorties du code).
- M+ (DungeonRoute / MDT).
- UI web locale.
- Releases et installation en une commande.

## Jalons
- **v0.1** = S1, S2, T1 → T3 : les timelines Élém d'un boss. Premier truc utile, et vite montrable.
- **v0.2** = S3, R1 → R3 : Top Gear sur le vrai combat.
- **v0.3** = T4, R4, P1.
- **v0.4+** = partie 3 et élargissement.

Prochaine brique : **S2** (client Warcraft Logs).


# QE Live's healing engine: what it models, against the top healers' logs

2026-10-20. Read-only audit of QuestionablyEpic (github.com/Voulk/QuestionablyEpic, HEAD 2de52dc, 2026-10-15). The
repository has no license (no LICENSE file, no `license` field): all rights reserved, so nothing of it is copied
here or in paf; this note describes it in our words, with its file paths. The question: ask its author for a license
to reuse the engine (1), or build our own healing model from the logs (2).

## What the engine is

Three model types, chosen per spec and content (`Player/CastModel.js`, `TopGear/Engine/TopGearEngine.ts`):

- **Default**: fixed stat weights times the gear's stats. No simulation.
- **CastModel ("Profile")**: a per-minute spreadsheet. Major cooldowns at a rate from their cooldown and talents,
  filler from a mana budget (pool over the fight length plus regen) capped by the time left on the GCD; each spell
  heals coefficient × stats × talent multipliers × (1 − a fixed expected overheal from its spell database, 3% to
  40%). Target counts are plain numbers with the AoE caps (`Generic/TargetScripts.ts`).
- **Sequences / ramps**: a 0.01 s time-step simulator over a scripted cast list of about 55 s (buffs, ticks, haste,
  crits, procs, mana, targets numbered 1 to 20; `Generic/RampBase.js`). Only Discipline still has a Top Gear branch
  for it, and its current model is set to Default.

| Spec | Model used for raid gear | Depth |
|---|---|---|
| Mistweaver Monk | CastModel (Yu'lon, Chi-Ji, an average raid health setting) | deepest CastModel |
| Restoration Shaman | CastModel (both hero trees, Ascendance, Healing Rain / Surging Totem, tier sets) | medium-deep |
| Preservation Evoker | CastModel, Flameshaper only | medium |
| Discipline Priest | stat weights; the ramp simulator (the only time-based model) values on-use trinkets | deep in concept, partly stale |
| Restoration Druid | stat weights (its CastModel only feeds the Theorycrafting page) | shallow in Top Gear |
| Holy Paladin | stat weights plus hard-coded talent bonuses | shallow-medium |
| Holy Priest | a static table of casts, HPS and overheal per spell | shallow |

It computes the average HPS of a gear set (Top Gear, trinket charts), a per-spell breakdown and mana per minute.
Its inputs are stats, talents, the spec's settings and Raid or Dungeon: **no damage profile**. Its log import only
keeps an overall HPS and the fight length to normalise scores.

## What it ignores, and what the logs say

- **The fight**: no timeline, no raid damage, cooldowns cast on cooldown or at a set rate, never on a spike.
  The logs give both: Nek'zali heroic's raid damage peaks at 0:35 (Possession Barrage, ×1.6) and 1:15 (Ritual Burn,
  ×1.7), and the top Restoration Shamans put Spirit Link on them (0:36, 1:18).
- **Overheal from the damage pattern**: a constant per spell. Measured on the top healers of Nek'zali heroic
  (paf.healroles, healing tables of 40 kills): 46 to 63% overheal per spec in the fast kills ranked by an Elemental's
  damage, 19 to 35% in the slower kills ranked by a Restoration Shaman's healing. Overheal depends on the raid and
  the kill far more than on the spell.
- **Several healers sharing the healing**: none. In those kills each healer does 19 to 38% of the healing, and the
  share of a spec moves with what the others bring.
- **Movement, positioning, encounter targets**: none.

## Recommendation: build our own (2), from the logs

A license would buy spell coefficients and talent maths, not prep: we would still have to build the fight layer it
lacks (damage input, timing, overheal from the damage, healers sharing), keep a Node sidecar of about 15k lines in
sync with its upstream every patch (1 to 2 weeks of integration, then ongoing), and its deepest models are not the
ones used for raid gear on half the specs.

Our own model fits the product and reuses what paf already has (the Warcraft Logs client, the raid damage per
second, the healers' casts and healing per kill since 0.8.12): replay the top healers' casts against the raid's
real damage, cap effective healing at the health deficit (overheal from the data, not a constant), share the
healing as the top raids do, and value stats and gear per spell from coefficients measured in the logs. About 3 to
4 weeks for a first spec (Restoration Shaman or Discipline Priest), then about a week per spec.

Not started: the goal asks for the user's go-ahead first. QE Live stays a reference for which mechanics matter per
spec (target caps, the mana budget, Mistweaver's sub-systems), and a link from our healer sheet for the value of a
talent or an item; contacting its author is worth it to cross-link the tools, not for a code license.

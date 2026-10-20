# Fight model audit: Encounter Journal and game data against the rebuilt fight

2026-10-20, paf 0.8.10 → 0.8.11. Every boss of every local corpus (The Venomous Abyss, 9 bosses; Elemental Shaman on
both difficulties, plus Subtlety, Assassination, Restoration Shaman and Protection Warrior where collected: 29 boss ×
difficulty × spec fights). For each one: `build_template` (the simulated fight) next to the Journal's stages,
creatures and abilities, every Journal spell's game-data effects (aura 87 *mod damage % taken*, followed one level
through triggered spells), the Warcraft Logs phases, every enemy unit with its death rate, and the raid's damage by
target.

The rule checked: **the same boss gives the same fight in every spec**, and every Journal mechanic that changes what
a damage dealer can hit (an amp, an immunity, a target) is in it or knowingly left out.

## What was wrong, and the fix (all generic)

| Boss | Gap | Cause | Fix |
|---|---|---|---|
| Sszorak | Dig In (+30% damage taken, game data) in the Subtlety fight, missing from the Elemental one | The logs' ratio had to reach ×1.3 before the game data was read: ×1.32 in the Subtlety logs, ×1.2 in the Elemental ones | 0.8.10: the game data decides first (`aura_amps`) |
| Nymrissa Wavecaller | No add at all, while the top Elementals put **60%** of their damage on Bubblefin Shorerunners (mythic: + Frostscales, 2%) | Adds are found by their deaths; the murlocs flee into the bubble and never die in the logs | Non-boss enemies taking ≥ 2% of the raid's damage over the corpus get their windows from the damage-taken graph (`npc_window`), their count from the instances spawned in each window (`undying_waves`): 15 every 45–65 s in heroic, 17 + 2 Frostscales in mythic, the same timeline from the Subtlety corpus |
| Nymrissa Wavecaller (count) | With the murlocs in, the top Elementals simmed at **1.63** of their real DPS | SimC cannot kill an add by damage: 15 murlocs stayed up for the whole 30 s window, every AoE hitting 16 targets. The top Elementals hit 5 at once (damage events, 3 s slices), each for about 10 s | The count of an add that never dies is how many of them the ranked players hit at once (`npc_stack`, 4 kills, as for a council), capped by the instances spawned |
| Entombed Sentinels | No immunity, while both Sentinels take −99% during Vitriolic Stasis at 46, 148 and 250 s | The phase table keeps a phase's first start only; the intermission comes back every ~100 s | A boss aura at −90% or less in the game data becomes an immune window unless a phase covers it (Nek'zali's Tether of Awakening matches its intermission kill by kill, so it adds nothing there) |
| Entombed Sentinels (sim) | With the Stasis immunities in, the top Elementals simmed at **0.33** | A Venom Coagulation spawned 0.8 s before the end of an immunity was still up when the boss came back; with `retarget=1` SimC then never returns to the boss | `Fight._spawns` also cuts an add spawned in an immunity's last second (it comes back 0.5 s after) |
| Zul'jan, Ula'tek, Vexhul | The boss notes proposed "possible amps" that are not: a second Ghastly Regeneration aura and the Soulbinding ritual (×3.65–5.5 inside the confirmed ×2.0 window), Rage of the Shackled (×1.32: the heart it exposes), Uncoiled Wrath (×1.34: a damage-*done* buff on the surviving serpent) | Candidates were any boss aura measured ≥ ×1.3 | A candidate is dropped when the game data knows the aura without a damage-taken effect, or when a confirmed amp covers it |
| Nek'zali heroic, Restoration / Protection corpora | Echo of Jawae missing, a ×1.0 "amp" instead | Those corpora had never been prepared: no damage graphs, no boss auras | Not a model bug: a prep fetches them first (checked: once fetched, the four specs give the same fight) |

## Checked and right

- **Venomous Heart** (Ula'tek): ×2.0 from the game data (the logs measure ×2.64), heroic and mythic.
- **Ghastly Regeneration** (Zul'jan): ×2.0 at 3:08 heroic, 6:31 mythic; Malacrass windows in Stage Two.
- **Nek'zali**: the intermission (Tether of Awakening, immune) and the Echo of Jawae, identical across the four specs
  within the kills' spread (heroic intermission 1:40–1:52 depending on the corpus' kills).
- **Vashnik**: Burning and Shrouded Venom waves; Malignant Totem (mythic) is not a damage target.
- **The Lost Explorers**: council of three, Useless Junk adds.
- **Sszorak**: Howling Maelstrom is a recurring phase (shown with `looped_phases` since 0.8.6), Dig In each time.

## Left out on purpose

- **Positional reductions**: United Defense (Lost Explorers, −99% within 30 yd of each other), Ula'tek's Dominance
  (Sentinels): the raid keeps the bosses apart; the top players' damage shows they do.
- **Reductions on adds** (Mother's Boon on the Blightscale Wretch, Waterfog Shield of the Frostscale): the add counts
  are calibrated on the top players' boss share instead.
- **Drowned Echo** (Nek'zali mythic): 3.7% of the raid's damage but under 0.5% of the top Elementals' and
  Assassination Rogues': another role's job.

## Open

- **Two-boss fights**: settled by measurement in 0.8.16 (see "Every boss, two specs" below).
- **Damage-taken reductions between −10% and −90% on the boss** would be ignored (none in this tier).
- **Recurring phases** other than immunities are still kept at their first start in the corpus (only the display and
  the NSRT notes use `looped_phases`). The one boss with such a phase, Sszorak (Howling Maelstrom), validates at
  1.01 to 1.07 on both specs and difficulties: no visible cost, left as is.

## Bloodlust (issue #20)

The fight's Bloodlust was the median of the ranked player's own first lust buff. The corpus stores the buffs a
player gives themselves only (`player_buff` has a single source per kill), so a lust showed up only when the ranked
player cast it, and never when it was cast before the pull. Nek'zali mythic, Elemental corpus: a lust in 104 of 359
kills (the shamans' own); the Rogue corpora: none, so the fight said "at the pull" whatever the raids do.

`paf.corpus.lust` reads the lust buffs of the whole raid, one request per kill, 100 kills per boss: a lust is a buff
at least 8 players gain within 3 s that lasts 15 s or more (a 2 s Time Warp proc is not one); a lust cast before the
pull shows as buffs that only end, about 40 s in. Read on the real kills:

| Boss | Spots of the top raids |
|---|---|
| Nek'zali heroic | on pull 96% |
| Nek'zali mythic | start of Stage Two 48%, on pull 46%, none 1% (the bimodal case: the old median fell between the two) |
| Vashnik mythic | on pull 100% |

The rebuilt fight now plays the most used spot unless the raid lead picks another on the Raid lead page; each
spot's gain is simmed for the player's character during the prep.

## Checked on full preps (Elemental, heroic unless said)

| Boss | Simulated / real DPS of the top players | Notes |
|---|---|---|
| Nymrissa Wavecaller | 1.63 with the murlocs as 15 targets for each whole window; **1.04** with the count the top players hit at once (5) | the boss share stays high (61% simulated vs 41% real): SimC's target priority, as before. The top build with Earthquake now sims +48.7% over a single-target build; holding Ascendance for the murlocs +9% |
| Entombed Sentinels | 0.33 with the Stasis immunities and the last-second add bug; **1.13** fixed (the old packs without immunities: 1.03 Subtlety, 1.18 Elemental mythic) | the intermission that comes back three times is now drawn three times (`immune_phases`) |
| Nek'zali mythic | **1.03** | Bloodlust on pull sims +3.7% over the start of Stage Two for this Elemental: that lust overlaps a long movement window (3:57 to 4:34) |

## A raid like yours (issue #26)

`paf.killtime`: the fight of a slower raid is rebuilt from the slower kills of the corpus (every corpus query
reads them only, `slower_kills`): as slow as the raid's last kill of the boss when known, else the slowest quarter
of the top kills, never fewer than 30 kills. It is a second sheet (same plans, their presses replayed on it, its own
phases, waves, boss casts and notes), and every plan is also simmed on it as a sensitivity variant. Nek'zali
heroic: 4:16 → 5:14 with the intermission at 2:06 instead of 1:42 and a wave of 18 Restless Amani logged 0.8 s
before Stage Two (which surfaced the boundary rule now in `Fight.__post_init__`).

## Every boss, two specs (paf 0.8.16)

Every fight rebuilt with the current code, then calibrated as a prep does (the add counts scaled until the simulated
boss share matches the spec's real one), then 4 top players of the spec simmed on it with their own gear, talents and
real secondary stats. Simulated / real DPS, median (range):

| Boss | Heroic, Elemental | Heroic, Subtlety | Mythic, Elemental | Mythic, Subtlety |
|---|---|---|---|---|
| Nymrissa Wavecaller | 1.04 (1.00-1.08) | 0.85 (0.81-0.85) | 1.11 (1.07-1.20) | no corpus |
| Nek'zali the Soulcoiler | 0.95 (0.91-0.96) | 0.89 (0.81-1.00) | 0.96 (0.93-1.00) | no corpus |
| Entombed Sentinels | **0.89** (0.89-0.93), was 1.13 | **1.00** (0.97-1.04), was 1.31 | **0.87** (0.85-0.90), was 1.09 | no corpus |
| The Lost Explorers | 0.91 (0.87-0.93) | 1.06 (0.99-1.09) | 0.93 (0.90-0.97) | no corpus |
| Vashnik the Malignant | 0.90 (0.79-0.94) | 0.94 (0.87-0.97) | 1.01 (0.95-1.03) | 1.10 (1.06-1.16) |
| Sszorak | 1.01 (0.95-1.03) | 1.03 (1.00-1.04) | 1.07 (0.97-1.09) | no corpus |
| The Coiled Altar | 1.02 (0.99-1.08), was 1.05 | no kills in the corpus | 0.88 (0.87-0.90) | no corpus |
| Ula'tek | 0.90 (0.82-0.93) | no kills in the corpus | 1.03 (1.00-1.06) | no corpus |

Every median between 0.85 and 1.11. What the run found and fixed:

- **A run without the add calibration is not what a prep sims.** Nymrissa simmed at 1.41 for the Subtlety Rogues
  before calibration: their real boss share is 94% (the murlocs are the ranged players' job; 6% of a Rogue's
  damage), the fight's 5 murlocs at once came from the Elementals (who hit 5; the Rogues hit 4 when they do, 2 to
  5). Calibrated on their share (add counts ×0.2), 0.85.
- **Two bosses the raid keeps apart are not two targets.** Entombed Sentinels' second boss (Blood of Ula'tek) was a
  target beside the first for the whole fight: every cleave hit both, 1.31 of the real DPS for the Rogues. Measured
  on 6 kills a spec, the top Elementals and Rogues hit one Sentinel at a time (the Journal's United Defense: the raid
  keeps them apart). `boss_units` now finds a fight with two or more bosses at their own health (a council, or a
  50/50 pair that `council()` misses), the prep measures how many the top players hit at once, and a second boss
  hit alone, up while the first one is attackable, is single target, not a cleave target (`bosses_hit_at_once`).
  One up while the first is immune stays a target: Nek'zali's Echo of Jawae in her intermission (also "one at a
  time" in the logs, for that reason). Measured on every multi-boss fight: The Lost Explorers 2 (council, as
  before), The Twin Fangs 2 (Vexhul and Ithraz stacked: unchanged), The Coiled Altar 1 (Hex Lord Malacrass no longer
  a cleave target: 1.05 → 1.02), Ula'tek and her heart 1 (the heart is a damage amp, unchanged).
- **A ranked log made private stopped the whole validation** (The Coiled Altar and Ula'tek mythic): the player is
  now skipped.

Open: the Subtlety corpus has no mythic kills and no heroic kills of two bosses; Nymrissa heroic's Rogues sim at the
low end (0.85, the add scale at its floor ×0.2: SimC's target priority keeps some damage on the murlocs).

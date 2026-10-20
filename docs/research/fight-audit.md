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

- **Two-boss fights** (Sentinels, Vexhul and Ithraz): `council()` needs no boss over 50% of the boss damage, which
  two even bosses miss by construction (50.3%). They are modeled as a boss plus windows on the other one. Raising the
  threshold would also turn Ula'tek and her heart (58% in mythic) into a council; the validation (simulated / real
  DPS of the top players) decides, see below.
- **Damage-taken reductions between −10% and −90% on the boss** would be ignored (none in this tier).
- **Recurring phases** other than immunities are still kept at their first start in the corpus (only the display and
  the NSRT notes use `looped_phases`).

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

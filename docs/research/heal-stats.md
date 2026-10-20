# Healer compositions across every corpus (2026-10-20)

Question: do some healer compositions kill faster than others, once the boss, the difficulty, the raid's size and
item level (and, where possible, the guild) are accounted for? Read on every local corpus at once: the corpora of
10 specs share most of their kills, so the kills are deduplicated (report, fight).

## Data

- **7,225 unique kills** of the top raids (The Venomous Abyss, 9 bosses): 4,719 heroic, 2,506 mythic. Outcome: the
  kill's duration (log), so every effect reads as a percentage of kill time.
- Healers of a kill: the corpus' `player` table, which comes from the **damage** table. A healer who deals no damage
  is missing from it. Measured on the 712 kills that also have the healing tables: **9% of the healers are missing**
  (Holy Priest 18%, Restoration Shaman 17%, Holy Paladin 2%, Discipline Priest 0%). The counts below are therefore
  slightly low; every finding is checked again on those 712 kills, where the healers are complete.
- Only kills: a composition that made a raid wipe is not in the data (survivorship). The numbers say what goes with
  faster kills among the raids that killed, not what makes a raid kill.

Method: ordinary least squares on log(duration), one dummy per boss and difficulty, raid size (heroic is flexible)
and average item level as controls, then the number of healers (or the number of each healer spec). Raid size held
constant, one more healer means one fewer damage dealer. A second model absorbs the **guild** (fixed effects, guilds
with 5 kills or more: 110 heroic, 76 mythic), so that a composition is compared within the same raid team. Script:
pure Python, no numpy (the app's dependencies stay minimal).

## Findings

**1. A healer instead of a damage dealer goes with a slower kill, on almost every boss.**

| | all kills | within a guild | kills with complete healers |
|---|---|---|---|
| heroic | +3.9% per healer (±0.4) | +1.5% (±0.8) | +6.3% (±1.0, both difficulties) |
| mythic | +2.6% (±0.6) | +5.2% (±1.5) | |

(95% intervals.) It survives the guild control: the same raid team kills faster on the nights it brings one healer
fewer. It is smaller than a damage dealer's share (1/15 of the damage is about 6.7%): a healer deals some damage
too.

**2. Per boss, the cost of a healer differs a lot** (all kills, controls as above):

| Boss | HM healers, median (p25-p75) | HM per healer | MM healers | MM per healer |
|---|---|---|---|---|
| Nymrissa Wavecaller | 5 (4-6) | +7.7% (±1.7) | 5 (4-5) | +5.2% (±1.9) |
| Vashnik the Malignant | 4 (3-5) | +7.0% (±0.8) | 5 (4-5) | +1.3% (±1.0) |
| The Twin Fangs | 4 (3-5) | +4.6% (±1.3) | 4 (4-4) | -1.2% (±1.4) |
| Nek'zali the Soulcoiler | 4 (3-5) | +3.3% (±0.7) | 4 (4-4) | +2.1% (±1.5) |
| The Lost Explorers | 4 (3-5) | +3.3% (±1.4) | 4 (3-4) | +2.9% (±2.0) |
| The Coiled Altar | 4 (4-5) | +2.1% (±1.3) | 5 (4-5) | +4.8% (±1.3) |
| Sszorak | 4 (3-5) | +1.8% (±1.2) | 4 (4-4) | +2.5% (±1.5) |
| Entombed Sentinels | 4 (3-5) | +1.7% (±1.6) | 4 (4-4) | -0.3% (±1.8) |
| Ula'tek | 5 (4-5) | -0.3% (±0.6) | 4 (4-4) | +0.0% (±0.9) |

On Ula'tek a fifth healer costs nothing measurable (heroic and mythic); on Nymrissa and Vashnik heroic each healer
costs about 7% of kill time. Mythic raids converge on 4 healers on most bosses, 5 on Nymrissa, The Coiled Altar and
Vashnik.

**3. No healer spec makes kills faster, once the guild is accounted for.** Across all kills, Preservation Evoker
(+1.1% per healer, heroic) and Mistweaver Monk (+2.1%) looked cheaper than the others (+3.6 to +4.3%), and Discipline
Priest, Preservation and Mistweaver too in mythic (+0.2 to +1.0% against +2.6 to +3.3%). Within a guild these gaps
vanish: every spec's interval overlaps the others' (heroic: Holy Paladin +2.3 ±1.3, Restoration Shaman +2.4 ±1.2,
Preservation +0.8 ±1.5, Mistweaver +1.0 ±1.7...). Most likely the cheap specs were the stronger guilds' picks, not faster by themselves.
The one exception, Discipline Priest within a guild in heroic (-5.5% ±2.6), rests on few guilds that switch to it
and is not confirmed in mythic (+2.5% ±3.0).

## What it means for the sheets

- The healer sheet's composition table (paf.healroles.presence) compares kills with and without each spec without
  the guild: its gaps mostly measure who plays the spec. It already says "a reading, not a verdict on the spec"; the
  study confirms it should never rank the specs.
- The healer count per boss (finding 2) is a measured, useful number for a raid leader ("Ula'tek: a fifth healer
  costs nothing; Vashnik heroic: about 7% of kill time each"). Proposed for the raid lead page, not done yet: it is
  a game-facing claim, to be checked with the owner first (survivorship: a raid that drops a healer on Vashnik may
  wipe instead).

## Open questions

- Survivorship: the wipes of the same guilds (in their reports) would tell whether fewer healers wipe more. Reading
  them costs Warcraft Logs quota (about 2 points a report for the fights list); not done.
- Deaths per composition need the healing tables (heal_kill), read for 40 kills on 2 bosses per healer corpus only.

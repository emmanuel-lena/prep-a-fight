# SimC lab findings: simulating a specific boss fight (Elemental, nightly 1210-01, WoW 12.1.0.69933)

Test bed: `profiles/MID2/MID2_Shaman_Elemental.simc` (Farseer, 4pc), 32-thread i9. Lab files: `scratchpad/simc_lab/` (`fight1c.simc`, `ps_apl.simc`, `ps_tal.simc`, `gen_apl.py`). The personal export was not used in any output.

## 0. Traps found (read first)

1. **`fight_style=Patchwerk` wipes `raid_events`.** With it in the fight file, the report has no "Raid Events" section and no adds spawn. If you leave `fight_style` out, the header shows `fight_style=None` and the events run.
2. **`last=` is exclusive.** `first=65,...,last=65` means the wave never fires. `first=30,cooldown=40,last=110` fires at 30 and 70, not 110. For one-off waves, use `cooldown=9999` and leave out `last`.
3. **Adds cannot be killed by damage (raid_event `adds`).** `health=2000000` is accepted without a warning but ignored: the debug log shows `MaxHealth=0` for adds. One add soaked 5.0M damage and still lived its full `duration`, with `fixed_time=0` or `1`. `add_health`, `enemy_health` and `health_percentage` give `Unknown raid event ... option ..., ignoring`. **Add lifetime = `duration=`** (taken from the log: first damage → death). Only DungeonRoute `pull` enemies have real HP.
4. Git Bash rewrites `raid_events=/adds...` passed on the CLI into `C:/...` (`Invalid raid event type 'C:'`). Use `MSYS_NO_PATHCONV=1` or put the events in a file. PowerShell is not affected.
5. Profileset names given on the CLI keep their double quotes in the output (`"lust60"`). Names in a file do not.
6. The text report labels priority DPS as **`DTPS=`**. Its value is exactly `prioritydps`.

## 1. JSON (`json2=`) paths

| Need | Path |
|---|---|
| total DPS | `sim.players[0].collected_data.dps.mean` / `.mean_std_dev` |
| boss-only (priority target) DPS | `sim.players[0].collected_data.prioritydps.mean` (present when adds exist; on a pure 1-target run the key is absent/None) |
| fight length | `collected_data.fight_length.mean` |
| per action | `sim.players[0].stats[]`: `name`, `num_executes.mean`, `portion_aps.mean` (DPS contribution), `portion_amount` (share), `actual_amount.mean`, `direct_results.{hit,crit}...`; pets in `stats_pets` |
| buff uptime | `sim.players[0].buffs[]`: `name`, `uptime` (%), `start_count`, `refresh_count`, `duration`; plus `buffs_constant[]`. Names can repeat (pets' `movement`), so filter by name and take the first match. |
| per-target breakdown | **none**. `sim.targets` holds only the boss; adds and raid events are not in the JSON. Per-target damage is only in `log=1` (`hits Enemy 'Fluffy_Pillow_wave11' for X`). |

**Profilesets:** `sim.profilesets.metric` and `results[]` = `{name, mean, min, max, stddev, mean_stddev, mean_error, median, first_quartile, third_quartile, iterations, additional_metrics[], overrides}`. **`profileset_metric=dps,prioritydps` works.** The first metric ranks the profilesets; the others come back as `additional_metrics[i] = {metric:"Damage per Second to Priority Target/Boss", mean, mean_error, median, ...}` (the label is text, not a key, so index by the order you asked for). `profileset_output_data=all` adds `overrides.stats`, but the values are garbage (denormals like `1.15e-311`, a bug). Don't use it. No per-action or per-buff data is given per profileset.

## 2. Reproducing the fight (verified via `log=1`)

`fight1c.simc` (5:40, 3 waves, 2 movements):
```
max_time=340
fixed_time=1
vary_combat_length=0
desired_targets=1
raid_events+=/adds,name=wave1,count=3,first=65,duration=22,cooldown=9999
raid_events+=/adds,name=wave2,count=3,first=170,duration=25,cooldown=9999
raid_events+=/adds,name=wave3,count=5,first=270,duration=18,cooldown=9999
raid_events+=/movement,first=120,cooldown=9999,duration=6
raid_events+=/movement,first=230,cooldown=9999,distance=20
```
Log: `65.000 wave1 (id=0) starts.` → `summons wave11/12/13 for 22.000s` → `87.000 ... demises` / `wave1 finishes`; `170 wave2 starts`, `195 finishes`; `270 wave3 starts` (5 adds), `288 finishes`. Movement: `120 movement_distance starts` / `126 finishes` (duration mode). The distance mode starts and finishes at 230 but applies the `movement` buff, and Spiritwalker's Grace is cast at 231.05. Fight length is exactly 340.0. Durations are exact (no stddev by default).
Result (1000 iter): **DPS 276,922, prioritydps 223,873**. Plain Patchwerk 300s ±20%: 250,112.

Other verified syntax:
- `adds,...,timestamps=30:90:150` works (starts at 30/90/150, each lasting `duration`). This gives one line per add type with irregular times.
- `raid_events+=/invulnerable,first=150,duration=12,cooldown=9999`: the boss gets the buff for 150–162, and 0 damage hits the boss in that window. DPS 266,890 / prio 216,295.
- **Bloodlust:** `bloodlust_time=60` → lust at 60.000 (log: `gains Buff 'bloodlust'`). `bloodlust_time=-60` → lust at 281 (end − 60 + 1s). `bloodlust_percent=30` alone still lusts at 0 (it is an OR with the time condition, and default time = 0). No lust: `override.bloodlust=0` or `bloodlust_time=1000` (both 267.0k vs 276.9k).
- **Power Infusion:** `external_buffs.power_infusion=10/130/250` works. You get 3 PIs of 15s each: 10–25, 130–145, 250–265. **The separator must be `/`**: `10:130:250` and `10,130` silently keep only the first time. Gain: +7.2k DPS (+2.6%).

## 3. Talents

- `class_talents=`, `spec_talents=`, `hero_talents=` take **snake_case names : rank**, `/`-separated, and are **applied on top of** `talents=`. I checked this by diffing the HTML talent tables: `spec_talents=echo_chamber:0` changes only Echo Chamber. Tree/point validity is not checked, so a removed point is not re-spent. A display name fails: `Invalid 'spec_talents': Unable to find spec talent 'Echo Chamber'` (same for a bogus name). Names = the talent name lower-cased with `_` (from the HTML "Talents" table).
- `save_talents=f.simc` writes the resulting full `talents=` string, so you can turn name edits into an import string.
- In profilesets both work: `profileset."sb"+=talents=<string>` and `profileset."x"+=spec_talents=earthen_rage:0`. 10 profilesets on the fight above (target_error=0.2, threads=32):

| profileset | DPS | err |
|---|---|---|
| base | 277,076 | 528 |
| no_earthen_rage | 273,242 | 524 |
| no_fote | 271,001 | 538 |
| no_echo_chamber | 267,648 | 525 |
| no_inferno_arc | 267,140 | 517 |
| no_final_calling | 266,001 | 512 |
| no_mote | 261,659 | 504 |
| no_storm_frenzy | 258,633 | 499 |
| stormbringer_str (full string) | 254,137 | 482 |
| feedback_2 | 247,310 | 491 |
| no_eb | 205,109 | 392 |

## 4. APL

- `save_actions=f.simc` dumps the APL (82 lines). `save=f.simc` dumps the full profile. For a profile with no `actions` lines, the auto-generated APL is **identical** to the one shipped in MID2_Shaman_Elemental.simc. The lists are `precombat`, default, `aoe`, `single_target` (there is **no `cds` list**, so CD edits go into `single_target`/`aoe`).
- **A profileset can redefine an action list.** The first line uses `=`, the next lines use `+=/`:
```
profileset."no_asc"+=actions.single_target=stormkeeper,if=...
profileset."no_asc"+=actions.single_target+=/ancestral_swiftness
...
profileset."no_asc"+=actions.aoe=stormkeeper,if=...
```
(`gen_apl.py` builds these from the dump.) Checked: profileset `no_asc` = 234,346 and the same lines on the main actor = 234,325, with `ascendance` executes = 0 and SK = 8.0.
- Variants on fight1c (target_error 0.2), DPS / prioritydps:

| plan | DPS | boss DPS |
|---|---|---|
| default APL | 276,387 | 223,813 |
| SK held if `raid_event.adds.in<20` (`stormkeeper,if=(active_enemies>1\|raid_event.adds.in>20)&(...)`) | 281,166 (+1.7%) | 223,342 |
| Ascendance only with adds (`(active_enemies>1\|fight_remains<20)&(...)`) | 279,333 (+1.1%) | 212,233 (−5.2%) |
| no Ascendance | 234,346 (−15%) | 183,740 |

This shows why the **ranking metric must be chosen**: holding Ascendance for adds raises total DPS but lowers boss DPS.

- **Sim-level options apply per profileset**, because each one rebuilds the sim. `profileset."x"+=bloodlust_time=270` → 278,181; `+=override.bloodlust=0` → 267,334; `+=raid_events+=/adds,...` (extra wave) → 294,768. So lust timing, PI timings and fight variants can all be profilesets.

## 5. Performance (340s fight, fixed length)

- Baseline alone at target_error=0.2 needs about 1,050–1,140 iterations: 0.22s of sim, **0.42s wall** (threads=16 or 32, same).
- Baseline + 10 talent profilesets, target_error=0.2, threads=32:

| profileset_work_threads | wall |
|---|---|
| 1 (default) | 4.0s |
| 2 | 2.9s |
| 4 | 2.7s |
| 8 | 2.6s |

At this run size, start-up cost dominates. `profileset_work_threads=2..4` gives about −30%, and more barely helps. Around 40 profilesets on one boss profile should take about 10–15s.
- 1000 iterations of 340s with 3 profilesets: about 0.25s per profileset.

## 6. Ready-to-use recipe for the WCL → SimC generator

```
# boss_<name>.simc  (no fight_style line!)
max_time=<kill_s>
fixed_time=1
vary_combat_length=0
bloodlust_time=<lust_s>
external_buffs.power_infusion=<t1>/<t2>/<t3>
raid_events+=/adds,name=<w1>,count=<n>,first=<t>,duration=<life_s>,cooldown=9999
raid_events+=/movement,first=<t>,duration=<s>,cooldown=9999
raid_events+=/invulnerable,first=<t>,duration=<s>,cooldown=9999
```
Run it with `profileset_metric=prioritydps,dps` (or `dps,prioritydps`) and `profileset_work_threads=4`. Read `results[].mean` and `additional_metrics[0].mean`.

Not tested: `vulnerable` events, the `absorb` raid event, DungeonRoute pulls used as killable boss adds, and `external_buffs.pool`.

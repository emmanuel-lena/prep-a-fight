# prep-a-fight (`paf`)

**A free tool made by a raider, for raiders: prepare your boss fight in 5 minutes instead of 2 hours of logs.**

Before a new boss you usually dig through logs to see what the best players of your spec do, then you sim
your gear on a target dummy and hope it holds up on the real fight. prep-a-fight does that homework for you:

- it looks at what the top players of your spec actually do on that boss (Warcraft Logs);
- it rebuilds that fight (duration, add waves, phases, Bloodlust) for SimulationCraft;
- it tells you which gear and which cooldown plan work best *on that fight*, taking your raid assignments
  into account.

| Part | Question it answers |
|---|---|
| Timelines | What do the top players of my spec do on this boss, and when? |
| Sims | Which of my items are best on *this* fight, not only on a target dummy? |
| Prep | What is my plan for this boss, with my own assignments? |

Everything runs on your own PC, with your own free Warcraft Logs API key. Nothing to pay, no account.

### Where it fits

prep-a-fight is meant to sit **next to** the tools you already use, not replace them:

- **Raidbots** remains the easiest way to sim on standard fight styles, with no install. prep-a-fight
  adds fight-specific sims built from real logs.
- **Warcraft Logs, Lorrgs, WoWAnalyzer** show you logs and timelines. prep-a-fight turns that information
  into gear and cooldown recommendations for your character.
- It is built on **SimulationCraft**, the open-source engine behind most WoW sim tools.

> Status: early development. First target: Elemental Shaman, one boss at a time. See [ROADMAP.md](ROADMAP.md).

## Install

Requires Python 3.11+.

```sh
git clone https://github.com/emmanuel-lena/prep-a-fight
cd prep-a-fight
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -e .
paf setup                       # downloads the latest SimulationCraft nightly (Windows)
```

On Linux/macOS, `paf setup` is not available yet: use the official Docker image
(`simulationcraftorg/simc`) or build simc, then pass `--simc /path/to/simc` or set `PAF_SIMC`.

Note: the SimulationCraft nightly host only serves plain HTTP, so the download is not TLS-protected.

### Warcraft Logs credentials

1. Create a client at <https://www.warcraftlogs.com/api/clients> (any redirect URL, e.g. `http://localhost`;
   leave "Public Client" unchecked).
2. Put the credentials in a `.env` file at the project root (it is git-ignored):

```
WCL_CLIENT_ID=...
WCL_CLIENT_SECRET=...
```

3. Check everything with `paf doctor`.

## Prepare a boss

In your browser:

```sh
paf serve                    # opens http://127.0.0.1:8765: paste your /simc, pick a boss, tick your
                             # assignments (kick, soak...), run: the prep sheet opens when it is ready
```

Or in one command:

```sh
paf profile                  # in game: /simc, Ctrl+A, Ctrl+C, then this (reads the clipboard)
paf prep "Ula'tek" --open    # everything below, as a one-page HTML prep sheet
```

The prep sheet gives:
- the fight: phases, add waves, lust, and the boss's mechanics;
- your DPS on the rebuilt fight vs a Patchwerk;
- a validation: the top players' own characters simmed on the rebuilt fight vs their real DPS;
- the top players' talent builds simmed on your character;
- the **ideal cooldown play-by-play for boss damage, total damage and damage to adds**, with an MRT note;
- what the top players actually do with their cooldowns;
- your best items and what the boss drops for you;
- a short "what to remember" list at the top.

## Or step by step

```sh
paf profile                  # in game: /simc, Ctrl+A, Ctrl+C, then this (reads the clipboard)
paf corpus "Ula'tek"         # collect ~200 ranked kills of your spec from Warcraft Logs (resumable)
paf analyze "Ula'tek"        # fight shape, add waves, who hits adds, talent pick rates
paf timeline "Ula'tek" --open  # cooldown timelines of the top players, as an HTML page
paf template "Ula'tek"       # the typical fight, rebuilt for SimC (editable JSON)
paf topgear --boss "Ula'tek" --preset patchwerk   # your best items on that fight
paf talents "Ula'tek"        # the top players' builds simmed on your character
paf cdplan "Ula'tek"         # cooldown plans compared on that fight
```

## Commands

| Command | What it does |
|---|---|
| `paf setup` | Download / update SimulationCraft into `~/.paf/simc/` |
| `paf doctor` | Check simc, Warcraft Logs credentials and your API quota |
| `paf config [key value]` | Settings: default difficulty, class/spec, corpus size, region |
| `paf profile [file]` | Load your character from the `/simc` export (clipboard, file, or `-` for stdin) |
| `paf corpus BOSS` | Collect ranked kills of your spec: fight, phases, adds, damage per target of every player, talents, gear, and the ranked player's casts with positions and buffs. Stored in `~/.paf/corpus.sqlite`. `--ilvl 318` samples players around an item level instead of the top. |
| `paf analyze BOSS` | Phases, add waves across kills, share of damage on adds for every spec, talent pick rates |
| `paf timeline BOSS` | Lorrgs-like HTML page: fight strip (phases, add waves, boss abilities), when the top players use each cooldown, one row per player. Cooldowns are detected automatically. |
| `paf template BOSS` | Typical fight for SimC: duration, add waves (time, count, lifetime), intermission, lust, Power Infusion, movement windows from the top players' trajectories. Edit the JSON to customize it. |
| `paf sim BOSS` | Your character on that fight vs a Patchwerk of the same length (total and boss-only DPS) |
| `paf topgear` | Best combination of your items (bags, great vault, linked items) on boss fights and/or presets; `--objective boss` ranks on boss-only damage |
| `paf talents BOSS` | Most common builds of the top players simmed on your character, with the talents they change vs yours |
| `paf cdplan BOSS` | Cooldown plans (default APL, on cooldown, hold for adds, top players' timings) compared on the fight |
| `paf calibrate BOSS` | Scale the add counts so your simulated share of damage on the boss matches the top players' logs |
| `paf plan BOSS` | Your own plan on top of the template (moves, soaks, lust, PI) in a text file; `--optimize` finds the best timing of the moves you mark as shiftable |
| `paf droptimizer` | Value of every item the raid (or `--boss`) drops for you, on the fights you choose; EV per boss |
| `paf mechanics BOSS` | The boss's mechanics from the in-game Encounter Journal (roles, interruptible, mythic...); `--corpus` adds who handles each one in the top kills (assigned, several players, raid-wide, kicks) |
| `paf assigns BOSS` | Mechanics you can be assigned to, with their timings and their cost (movement) measured on your spec in the logs; adds `# assign ...` lines to your plan file |
| `paf validate BOSS` | Sims the top players' own characters (gear, talents, real stats from their logs) on the rebuilt fight and compares with their real DPS; `--calibrate` fixes the inferred movement accordingly |
| `paf optimize BOSS` | Ideal cooldown rules per objective (boss / total / adds): on cooldown, hold for adds, secondary targets, lust/PI...; play-by-play and MRT note |
| `paf prep BOSS` | All of the above for one boss, as an HTML prep sheet |
| `paf serve` | Local web UI for all of this |

### How much to trust the numbers

- Every delta comes with SimC's statistical error; smaller differences are noise.
- A rebuilt fight is an approximation: add lifetimes and movement come from the top players' logs,
  and SimC has no fine target priority. Good for choosing between builds, items and plans; not a
  prediction of your exact DPS.
- `paf validate` tells you how close the rebuilt fight is to reality: on Ula'tek heroic, the top 6
  Elementals simmed with their own gear reach 97% of their real DPS once the movement is calibrated.
- SimC does not know that a secondary target (a heart, a shield) must die fast: compare the simulated
  plans with what the top players do (shown next to them).
- Analyses of the corpus are correlations (what the top players do). SimC is used to check them on
  your character.

## License

MIT. SimulationCraft is a separate GPL-3.0 project, downloaded from its official site, not redistributed.
World of Warcraft is a trademark of Blizzard Entertainment; this project is not affiliated with Blizzard
or Warcraft Logs.

---

### En bref (FR)

Outil gratuit, fait par un raider pour les raiders : préparer un boss sans passer 2 h dans les logs. Timelines des meilleurs logs de ta spec, sims
sur le vrai combat reconstruit depuis les logs, et plan de CD selon tes assigns. Complémentaire de Raidbots et Warcraft Logs, pas un remplaçant.
Installation ci-dessus, feuille de route dans [ROADMAP.md](ROADMAP.md).

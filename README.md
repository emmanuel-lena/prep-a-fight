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

Everything runs on your own PC, through your own free Warcraft Logs account. Nothing to pay, no new account.

### Where it fits

prep-a-fight is meant to sit **next to** the tools you already use, not replace them:

- **Raidbots** remains the easiest way to sim on standard fight styles, with no install. prep-a-fight
  adds fight-specific sims built from real logs.
- **Warcraft Logs, Lorrgs, WoWAnalyzer** show you logs and timelines. prep-a-fight turns that information
  into gear and cooldown recommendations for your character.
- It is built on **SimulationCraft**, the open-source engine behind most WoW sim tools.

> Status: beta. Every DPS spec (Elemental Shaman is the most tested), healers and tanks (from the top players' logs).
> See [ROADMAP.md](ROADMAP.md).

## Install (players, Windows)

1. Download **`prep-a-fight-setup-<version>.exe`** and run it (no admin rights needed, ~13 MB). It installs the
   app for your Windows user, with a Start menu entry, an optional desktop shortcut and an uninstaller.
2. Open **prep-a-fight**: the app opens in its own window (close it to stop it). On first launch it downloads
   SimulationCraft (~115 MB) in the background.
3. Click **Connect with Warcraft Logs** and log in, in your browser (the app reads public logs through your
   account and its hourly quota; it never posts anything). Then paste your `/simc` export and pick a boss.
   You can use your own API key instead (Settings).

Windows may show "Windows protected your PC" (SmartScreen) the first time: the installer is not signed with a
paid code-signing certificate yet. Click **More info**, then **Run anyway**. The installer is built from this
repository by `tools/build-installer.ps1` (Inno Setup and python.org's embeddable Python).

Beta testers: something broke or looks wrong? Open an issue with the **Beta report** form (it says which log to
attach).

To update, run the new installer over the old one. Everything stays in the folder you chose: the app in it,
your preps, caches and SimulationCraft in its `data` subfolder (about 1-2 GB with the caches, capped in Settings;
old sim folders and SimulationCraft versions are removed automatically). To uninstall: Windows Settings > Apps >
prep-a-fight; it asks whether to delete that data too.

A first prep of a boss takes about 7 minutes: it reads the first 100 ranked kills from Warcraft Logs (or a prep pack
another player shared this week), sims on your CPU, and the rest of the kills follow in the background. Later preps
of the same boss reuse everything.

## Using the app

**Prepare a boss**: on the home page, pick a boss and a difficulty, tick your assignments (kick, soak...) and go: the
estimate says where the data comes from and how long it takes, the prep sheet opens when it is ready.

**The whole raid in one press**: on the home page, *Prepare the whole raid* queues every boss (the ones already
prepared this week are kept) and says when it will be ready. Go and do something else: closing the app does not
stop it, an icon in the notification area shows where it is and a notification says when your raid is ready. After
the weekly reset, the app prepares the same bosses again by itself (setting `refresh_after_reset`).

**The week after**: when the app starts, it finds your character's last raid log on Warcraft Logs (no link to paste)
and reads it in the background: the night pull by pull, your rotation on the bosses you killed, why the others did
not die and your worst pull against your best. The home page opens on *Your last raid*: two or three things to clean
per boss. Tick the characters it reads on the Characters page.

**Raid lead**: from your raid's last log, the roles on every prepared boss: who hits which add, who changes talents
(boss or padding side, from the top players of each spec), which spec change is worth it; bench players in a click,
copy the whole thing for Discord or as an MRT note.

The prep sheet gives:
- the fight: phases, add waves, lust, and the boss's mechanics;
- your DPS on the rebuilt fight vs a Patchwerk;
- a validation: the top players' own characters simmed on the rebuilt fight vs their real DPS;
- the top players' talent builds simmed on your character;
- the **ideal cooldown play-by-play for boss damage, total damage and damage to adds**, with an MRT note;
- what the top players actually do with their cooldowns;
- your best items and what the boss drops for you;
- a short "what to remember" list at the top.

### Boss notes: what the logs cannot tell

Each rebuilt fight comes with `~/.paf/fights/<boss>-<difficulty>.notes.txt`, also editable in the web UI. It
lists what was detected, with the evidence (a unit sharing the boss's health and the damage amp measured in the
logs, possible amps on the boss...), and takes your corrections:

```text
amp Venomous Heart 2.0     # the real damage amp while the heart is up
separate Some Shield       # an independent priority target, not the boss's health
ignore Some Totem          # a mechanic, not a target
```

Plans that look too good (over 5%), that do not survive pessimistic variants of the fight (amp halved, adds dying
faster, more movement) or that contradict what the top players do are flagged "to double-check" in the prep sheet.

### How much to trust the numbers

- Every delta comes with SimC's statistical error; smaller differences are noise.
- A rebuilt fight is an approximation: add lifetimes and movement come from the top players' logs,
  and SimC has no fine target priority. Good for choosing between builds, items and plans; not a
  prediction of your exact DPS.
- The validation on the prep sheet tells you how close the rebuilt fight is to reality: on Ula'tek heroic, the top 6
  Elementals simmed with their own gear reach 97% of their real DPS once the movement is calibrated.
- SimC does not know that a secondary target (a heart, a shield) must die fast: compare the simulated
  plans with what the top players do (shown next to them).
- Analyses of the corpus are correlations (what the top players do). SimC is used to check them on
  your character.

## Install (developers)

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

The app's **Connect with Warcraft Logs** (OAuth with PKCE, `paf.wcllogin`) needs nothing here. From a terminal, or
to use your own key:

1. Create a client at <https://www.warcraftlogs.com/api/clients> (any redirect URL, e.g. `http://localhost`;
   leave "Public Client" unchecked).
2. Put the credentials in a `.env` file at the project root (it is git-ignored):

```
WCL_CLIENT_ID=...
WCL_CLIENT_SECRET=...
```

3. Check everything with `paf doctor`.

### The command line

The app runs its long work (preps, tools, the raid queue, the last raid) as `paf` commands in the background; the same commands work from a terminal, for development and scripting. They are not the players' interface: the app is.

In one command:

```sh
paf profile                  # in game: /simc, Ctrl+A, Ctrl+C, then this (reads the clipboard)
paf prep "Ula'tek" --open    # everything below, as a one-page HTML prep sheet
```

Step by step:

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

Every command:

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

## License

MIT. SimulationCraft is a separate GPL-3.0 project, downloaded from its official site, not redistributed.
World of Warcraft is a trademark of Blizzard Entertainment; this project is not affiliated with Blizzard
or Warcraft Logs.

---

### En bref (FR)

Outil gratuit, fait par un raider pour les raiders : préparer un boss sans passer 2 h dans les logs. Timelines des meilleurs logs de ta spec, sims
sur le vrai combat reconstruit depuis les logs, et plan de CD selon tes assigns. Complémentaire de Raidbots et Warcraft Logs, pas un remplaçant.
Feuille de route dans [ROADMAP.md](ROADMAP.md).

**Installer (Windows)** : lancer `prep-a-fight-setup-<version>.exe` (sans droits admin ; si SmartScreen bloque : « Informations complémentaires » puis « Exécuter quand même »), puis ouvrir **prep-a-fight** (une fenêtre d'application s'ouvre ; SimulationCraft se télécharge au premier lancement).
Au premier lancement, la page explique comment créer sa clé API Warcraft Logs gratuite (2 minutes), puis on colle
son `/simc` et on choisit un boss. Toutes les specs DPS sont prises en charge (le Chaman Élémentaire est la plus testée) ; pas encore les heals ni les tanks.

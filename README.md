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

## Commands

| Command | What it does |
|---|---|
| `paf setup` | Download / update SimulationCraft into `~/.paf/simc/` |
| `paf doctor` | Check simc and Warcraft Logs credentials |
| `paf profile [file]` | Load your character: in game type `/simc`, press Ctrl+A, Ctrl+C, then run `paf profile` (reads the clipboard). You can also drag a saved export file onto the terminal. The export becomes your current profile. |

More commands land brick by brick (see the roadmap).

## License

MIT. SimulationCraft is a separate GPL-3.0 project, downloaded from its official site, not redistributed.
World of Warcraft is a trademark of Blizzard Entertainment; this project is not affiliated with Blizzard
or Warcraft Logs.

---

### En bref (FR)

Outil gratuit, fait par un raider pour les raiders : préparer un boss sans passer 2 h dans les logs. Timelines des meilleurs logs de ta spec, sims
sur le vrai combat reconstruit depuis les logs, et plan de CD selon tes assigns. Complémentaire de Raidbots et Warcraft Logs, pas un remplaçant.
Installation ci-dessus, feuille de route dans [ROADMAP.md](ROADMAP.md).

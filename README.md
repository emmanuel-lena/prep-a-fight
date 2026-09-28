# prep-a-fight (`paf`)

**Prepare your boss fight in 5 minutes instead of 2 hours of logs.**

prep-a-fight looks at what the best players of your spec do on a given boss (Warcraft Logs), rebuilds that
fight for SimulationCraft, and tells you which gear and which cooldown plan work best *on that fight*:
not on a Patchwerk dummy.

Three parts, one local tool:

| Part | Inspired by | Question |
|---|---|---|
| Timelines | Lorrgs | What do the top players of my spec do on this boss? |
| Sims | Raidbots | Which gear, on *this* fight? (local SimC, your CPU) |
| Prep | — | My own plan for this boss, with my raid assignments |

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

More commands land brick by brick (see the roadmap).

## Legacy PowerShell Top Gear

`Invoke-LocalTopGear.ps1` is the original Windows-only prototype (local multi-profile Top Gear). Its
documentation is in [docs/legacy-topgear.md](docs/legacy-topgear.md). It will be replaced by `paf topgear`.

## License

MIT. SimulationCraft is a separate GPL-3.0 project, downloaded from its official site, not redistributed.
World of Warcraft is a trademark of Blizzard Entertainment; this project is not affiliated with Blizzard
or Warcraft Logs.

---

### En bref (FR)

Outil local pour préparer un boss : timelines des meilleurs logs de ta spec (façon Lorrgs), sims
Top Gear sur le vrai combat reconstruit depuis les logs (façon Raidbots), et plan de CD selon tes assigns.
Installation ci-dessus, feuille de route dans [ROADMAP.md](ROADMAP.md).

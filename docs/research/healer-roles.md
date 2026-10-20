# Healer roles and compositions from the logs (issue #27)

2026-10-20. `paf.healroles` reads, per kill (40 per boss, about 6 points each), every healer's healing and overheal,
their healing on the tanks (each tank's top sources in the healing table by target: a lower bound), their healing
during the raid's damage spikes (healing graph by source against the damage-taken graph, both bounded to the pull),
their dispels, the raid's deaths, and their long cooldowns (90 s or more in the game data) with whether they were
cast on another player. A spec gets a job line only when a number stands out against the other healers of the same
kills by a ratio **and** beyond two standard errors of its own healers, with at least 8 healers measured.

## Measured (heroic)

| Boss, corpus | Jobs that stand out |
|---|---|
| Nek'zali, Elemental kills (ranked by damage; ~4:05, 0 deaths) | Holy Priest gives externals (2.5 a kill, n=50); Preservation Evoker answers the spikes (38% of its healing in them against 30%, n=16) |
| Nek'zali, Restoration kills (ranked by healing; ~4:50, 2 deaths) | Holy Priest externals (2.9, n=26); Restoration Shaman wastes little (19% overheal against 32%, n=48) |
| Vashnik, Elemental kills | Holy Priest externals (2.8, n=54) |
| Sszorak, Elemental kills | Holy Priest externals (2.4, n=48); Restoration Shaman wastes little (26% against 37%); spikes: 1 to 3% for every spec (Sszorak has almost no raid damage spikes) |

The only job stable over every boss and corpus: the Holy Priest's externals (Power Infusion). Everything else moves
with the sample.

## Doubts, for the user

- **The sample changes the answer.** Nek'zali heroic, the same specs: overheal 46 to 63% in the fast kills ranked by an
  Elemental's damage, 19 to 35% in the slower kills ranked by a Restoration Shaman's healing (more to heal, a
  shaman doing 38% of it). The healer sheet says which kills it measured; which sample a healer should read (the
  fastest raids, or raids like theirs) is open.
- **Tank healing is a lower bound** (each tank's top sources only): 4 to 10% of every healer's healing on the three
  bosses. The "heals the tanks" job needs 12% or more and is shown nowhere yet.
- **Compositions**: exact healer compositions are scattered in heroic (flexible raid sizes): the sheet shows each
  spec's presence (kills with it against without it, deaths and kill time) rather than full compositions; the
  corpus' player table misses healers who never attack, so the healers come from the healing tables.
- **Healing Tide Totem**: cast in 3 of 100 top Restoration Shaman kills on Nek'zali heroic: the top players skip it
  this tier.

# Changelog

What changes for the players, release by release. Fixes and features land under "Unreleased" as they are done;
the weekly release (Tuesday) publishes that section as its patch notes (`python tools/release.py next --weekly`).

## Unreleased

- When Warcraft Logs is down, a prep no longer waits out every retry on each kill (it once took 55 min for one
  step): it stops that step with one line and reads the rest on a later prep. (#36)
- When the hour's Warcraft Logs quota runs out, the optional steps (who handles each mechanic, the raids' Bloodlust)
  no longer wait up to an hour for it: they stop, the prep finishes, and the rest is read on the next prep. (#34)
- A character whose /simc export is a week old or more shows its age, on the home page, on its card and on its
  picture in the side bar, with a link to update it. (#32)
- A prep done while you play: its notification now waits in the Windows notification center until you come back
  (Windows holds notifications back during a game), and the app's taskbar button lights up. (#33)
- Less to read, more to see: the healer and tank sheets show the big hits as a table with spell icons and size bars,
  shorter cards with one legend, and the other healers' answers as one table; the home page shows every sheet in
  one table (a spec a row, a boss a column).
- Best gear from your bags no longer drops a dual-wielder's off-hand weapon: a Rogue's sets all simmed one-handed
  (about -54%). A set list where everything loses more than 5% now says it is a failed sim.
- The fight tab says how many adds come as the logs count them (Nek'zali's 6, then 14 Restless Amani), not the
  sim's own scaled number (2, then 4).
- What a boss drops for you no longer lists items of another spec's main stat (an agility or strength weapon on an
  Elemental Shaman's sheet, at -17%).
- A cooldown plan whose small gain turns into a loss on a slower kill is no longer what the fight tab plays: it
  plays SimC's default list (Dig deeper still shows the plan and its checks).
- With your raid: when your character is in the raid's log as another spec (your alt), it is swapped for the one
  you prepare, never counted twice.
- Your class's other specs, when you pad the adds: the tiles compare total damage, as their heading says (they
  showed the boss-damage gap: Enhancement -12% for +4% in total).
- When your raid's log has you on another spec or another character, the sheet says so with a badge, reads you with
  the spec you prepare, and stands in for you at your raid's median damage dealer (not its fourth best).
- A defensive is never moved later than the top players press it (a Feint ran out before the hit it was for).
- A cooldown plan not robust enough to be played keeps its own MRT note and NSRT times on its card; gear and drops
  inside the sims' noise are no longer coloured as gains.
- Times read the same everywhere (cut to the second, as the MRT timers), and durations match the times shown.

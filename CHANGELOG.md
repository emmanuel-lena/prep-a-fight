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

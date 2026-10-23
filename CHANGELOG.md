# Changelog

What changes for the players, release by release. Fixes and features land under "Unreleased" as they are done;
the weekly release (Tuesday) publishes that section as its patch notes (`python tools/release.py next --weekly`).

## Unreleased

- When Warcraft Logs is down, a prep no longer waits out every retry on each kill (it once took 55 min for one
  step): it stops that step with one line and reads the rest on a later prep. (#36)

# Changelog

What changes for the players, release by release. Fixes and features land under "Unreleased" as they are done;
the weekly release (Tuesday) publishes that section as its patch notes (`python tools/release.py next --weekly`).

## Unreleased

- The opener lists your presses only: a Frost Mage's Frozen Orb and Flurry bolts (which SimC schedules like casts)
  no longer show as dozens of orbs on a one-minute cooldown. (#40)
- The opener is a timeline now, at the top of the fight tab: what you cast before the pull, your cooldowns on their
  own lane, your rotation under them, each icon at its time on a 40-second axis, Bloodlust as a band.
## 0.8.27 (2026-10-25)

- Settings, "Send a summary of each run" (off unless you turn it on): at the end of each prep or tool run, the app
  sends the maintainers how long each step took and the error if it failed, with your computer's CPU and memory; no
  character, guild, log or file name. It tells us what is slow or broken on players' computers.

## 0.8.26 (2026-10-25)

- The Gear tool tries every crafted piece your spec can wear in every slot, each in every Thalassian Missive (the
  stat pair read from the game data), and your own crafted pieces remade with each other missive: the item says
  which missive to craft ("craft, Crit/Mastery", "recraft, Haste/Versatility").
- The Gear tool's "Thorough" depth: more items kept per slot, up to 20,000 sets, the best ones simmed again at a fine
  error, then every swap tried from the best set until none gains (up to an hour on a desktop).

## 0.8.25 (2026-10-24)

- The fight tab shows the opener: every cast of the first 40 seconds in order, as SimulationCraft plays your plan,
  each with its icon and time (and whether Bloodlust goes out at the pull). (#39)
- Your class's other specs are compared with your own items: each spec's best set from your bags (the items of its
  main stat), against you as you are; the top players' set at 334 stays on the tile's hover as the ceiling. (#35)
- New "Gear" tool, in the side bar: paste a /simc (or use your character), pick a fight (a training dummy with 1 to 8
  targets and 3, 5 or 7 minutes, or a boss you prepared: its real fight), and it tells you what to equip from your
  bags and vault (with the crafted pieces the top players of your spec wear, at your crafts' stats), which of the
  enchants and gems they wear to change, then which drops of that boss (or the whole raid) to farm, ranked by their
  gain on top of that set. Top Gear gets the same dummy options and the paste box.
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
  one table (a spec a row, a boss a column); the goal choices carry an icon, and the raid lead page says the
  tanks and healers once, beside the roster. The DPS sheet's other talent builds of the top players say "other
  build · N talents apart" instead of listing 40 talents; its plans keep the MRT note and the NSRT copy button
  without the play-by-play table; the settings' help lines show on hover.
- More to see on the sheets: the healer chart draws a lane for each of your long cooldowns and trinkets, fainter
  where fewer top players press it; Your job on the DPS fight tab reads as time chips and badges (pre-pull, ⟲ a
  cadence, 🛡 a defensive, the boss immune); the boss tab's assignments and mechanics as chips (players hit, your
  odds, movement), each sentence on hover; Dig deeper's numbers as tiles. The healer and tank charts now draw
  every press (fainter where fewer top players press it, two rhythms as two lanes, Stasis's stores and releases),
  so the cooldown cards keep only what the chart cannot say (a press tied to a hit, "or", varying); each journal
  stage draws the boss's casts on a strip; the journal reads in two columns on a wide screen; talent builds
  within the sims' noise of yours are dimmed.
- Talents to take or drop no longer ask you to change a button the sim's rotation never presses (Purge, Tremor
  Totem, Blind, Tranquilizing Shot): they are set apart, in grey, as your choice, on the sheet and on the raid lead
  page.
- The boss pages open on the fight as one strip: the add waves with their count, the boss away, your moves and
  Bloodlust, on a timeline of the kill.
- The boss pages tell the Encounter Journal's words only for the abilities it flags for your role; the others keep
  their name, icon, tags and times, the name a Wowhead link to read them.
- What a boss drops for you is valued at the item level it can reach: at most 321 on heroic (the Hero track's top),
  334 on mythic, not at your own gear's level when it is higher.
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

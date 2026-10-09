# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: the **casual heroic raider** of World of Warcraft. Raids two or three evenings a week, wants to know what to do on a boss in five minutes before the pull, and is put off by tables, jargon and walls of numbers. When needs conflict, design for this player first; the details stay one click away, folded.

Also served, never at the primary user's expense:
- the mythic / parse player, who reads logs and wants every number and option (in the detailed tabs and the tools);
- the raid leader, who prepares the whole raid (who hits what, the best pull, the night's pulls, comps);
- healers and tanks, whose preps come from the logs of the top players of their spec.

## Product Purpose

Prepare a raid boss in minutes instead of hours of reading logs. For the player's own character and spec, the app reads the logs of the best players on that boss (Warcraft Logs), rebuilds the real fight (duration, phases, add waves, movement, Bloodlust), simulates the character on it (SimulationCraft), and gives a prep sheet: what to change (talents, gear), what to press and when (cooldown plan, defensives, precasts), what to watch (mechanics), what to look at in the raid's own logs (rotation review, pulls side by side, who hits what, the night's pulls).

Success: a player opens the sheet before the pull and plays the boss better, without having read a single log.

### The experience and the loop

- **Slippers comfort**: you open the app, press one button, go cook; when you come back, everything is ready to read. Long work runs on its own, in order, within the Warcraft Logs quota, and says when it is done. Nothing asks for a log link, a code or a choice the app can find itself.
- **Launching it is an experience**: opening the app feels like the start of the raid week, not like opening a tool.
- **People come back**: for the next boss, then the one after; and the week after, the app has already read the raid's logs and shows what to clean on the bosses still to kill.
- **The raid leader thinks about the strategy, not the roles**: the comp, who hits which add, who plays a single-target or an AoE build on each boss, come ready-made from the raid's own roster and logs, in a form that can be pasted to the raid.

## Positioning

The sims run on **the real fight rebuilt from the top players' logs**, not on a generic target dummy, on the player's own computer; and the prep goes past "which gear" to "what to do on this boss". Every analysis is generic across specs (driven by SimulationCraft's default rotations and the logs), not hand-written per class.

## Operating Context

- Used before a raid night (prep a boss) and after (review the raid's log, the night's pulls, a pull against another).
- A Windows desktop app (WebView2 shell serving the pages in process) is the main surface; the same pages work in a browser; phones only read a shared sheet.
- The player brings their character as a `/simc` addon export (the recommended way, it has the bags) or imports it from Warcraft Logs; several characters, one active at a time.
- Data sources: the player's own Warcraft Logs API key (3600 points an hour), SimulationCraft installed locally, game data tables from wago.tools, the Encounter Journal.

## Capabilities and Constraints

- **Runs locally**: the sims run on the player's computer with their own Warcraft Logs key; today no account is needed to use the app. User accounts may be added later (optional, for features that need one): designs must leave room for a signed-in state without making it required. Prep packs computed by players can be shared through a relay (computed numbers only, no raw logs, no names).
- **One player, one character**: the whole app follows the active character (its spec, its preps, its class color).
- **Desktop app first**, the browser second.
- A first prep of a boss takes minutes (collection paced by the Warcraft Logs quota); later preps reuse the corpus or a shared pack.
- English only until the 1.0; the French translation comes at the end.
- Open source (MIT).

## Brand Commitments

- Name: **prep-a-fight** (`paf` on the command line).
- Voice: plain, direct sentences addressed to the player ("you"), the numbers to the point; a reading, not a verdict ("a gap is a reading, not a fault").

## Evidence on Hand

- Measured results the app can state: a first prep in about 7 minutes; the rebuilt fight checked against the top players' real DPS (validation); precision by corpus size measured on real corpora.
- No testimonials, user counts or endorsements exist: none may be invented.

## Product Principles

1. **The player first, the expert one click away**: lead with what to do, in sentences; tables and raw numbers are folded details.
2. **Honest numbers**: every gain comes with its noise or confidence; under the noise, say nothing stands out; never invent a fact or a strategy the data does not show.
3. **The real fight**: everything is measured on the boss as the top raids play it, not on a dummy.
4. **Local at the core**: the sims and the prep run on the player's computer; accounts, if they come, stay optional.
5. **Generic, not hand-made per class**: one method for every spec, so every spec gets the same quality.
6. **Press once, come back to it ready**: the app does the long work by itself and finds what it can (the character's logs, the raid's roster, the next boss) instead of asking.

## Accessibility & Inclusion

WCAG AA basics: readable contrast in both themes, the whole app usable with the keyboard, reduced motion respected, no information carried by color alone (class colors and difficulty colors always come with a label or a shape).

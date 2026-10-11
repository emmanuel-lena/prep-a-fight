prep-a-fight: what it sends, and where
=======================================

prep-a-fight has no account, no analytics and no tracking. Everything it computes stays on your computer, in the
"data" folder of the place you installed it.

What it connects to
-------------------

- Warcraft Logs (warcraftlogs.com): to read the top players' public logs, and your own raid's logs, with your
  Warcraft Logs login or your own API key. The login stays on your computer; Settings > Disconnect forgets it.
- SimulationCraft (downloads.simulationcraft.org): to download the simulation engine, once and at its updates.
- wago.tools: the game's data (items, spells, the Encounter Journal).
- Wowhead (wowhead.com, wow.zamimg.com) and Google Fonts (fonts.googleapis.com, fonts.gstatic.com): the icons,
  tooltips and fonts of the app's pages. Like any web page, these requests show your IP address to those sites.
- GitHub (api.github.com, github.com): to check whether a new version is out and download it.
  Settings > "look for a new version of the app" turns it off.

What it sends
-------------

- Prep packs, unless you turn it off (Settings > "share the prep packs you compute"): the numbers a prep
  computes from the top players' public logs (the rebuilt fight, cooldown timings, talent builds), sent to the
  project's relay so the next player of your spec skips the log download. A pack holds no player name, no log code, no position, nothing
  about you or your character. Packs shared by others are downloaded the same way.
- A bug report, only when you write one and press Send in Feedback: your message, the app's version, your Windows
  and Python versions, and the end of the log of what you report, with your folders and keys removed.

Nothing else leaves your computer.

Uninstalling (Windows Settings > Apps > prep-a-fight) removes the app and asks whether to delete its data folder.

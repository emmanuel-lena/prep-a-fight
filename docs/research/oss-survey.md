# OSS survey for prep-a-fight (paf) — 2026-09-28

Method: GitHub API/raw files and wago.tools fetched directly. Items marked **(unverified)** come from memory or search snippets only.

## 1. REUSE (high value)

### Lorrgs backend — github.com/gitarrg/lorrgs
- Python (uv, pyproject), last push 2026-09-14, active. **No LICENSE file**, so by default all rights are reserved. Read it and re-type the ideas; don't copy code or data verbatim without asking the author (gitarrg, who is also a BigWigs contributor).
- **Already up to date for Midnight S2**: `lorgs/data/expansions/midnight/raids/the_venomous_abyss/ulatek.py` (plus 7 other bosses, other raids and dungeons). A boss is declared as `RaidBoss(id=3492, name="Ula'tek")` with `boss.add_cast(spell_id, name, duration, color, icon)` and `boss.add_buff(...)`. Ula'tek casts: Caustic Waves 1311807, Call of the Serpent 1304012, Spectral Coils 1308927, Mephitic Thrash 1296301, Mother's Wrath 1298367, Rage of the Shackled 1286860, Shadow Molt 1301213, Writhing Gestation 1302950, Grasping Fangs 1301117. Buffs: Venomous Heart 1299526, Defect: Weakened 1303410. Stage names are in comments/groups.
- Specs: `lorgs/data/classes/shaman.py` uses `SHAMAN_ELEMENTAL.add_spell(spell_id, cooldown, duration, color, icon, name, tags=[SpellTag.DAMAGE])`. Elemental tracks only **Stormkeeper 191634 (cd 60)** and **Ascendance 114050 (dur 15)**. Class-level and shared entries live in `externals.py`, `racials.py` and `consumables.py`. This is a good data model to copy as YAML (spell, cd, duration, color, icon, tag). Our list needs more entries (elementals, Primordial Wave, Liquid Magma Totem, Ancestral Swiftness, PI received, lust).
- WCL flow (`lorgs/loaders/`): `spec_ranking.py` calls `worldData{encounter(id){characterRankings(className, specName, metric, difficulty, includeCombatantInfo)}}` and turns the rankings into reports, then fights, then players. Fight window args are `fightIDs, startTime, endTime` (`Fight.table_query_args`). `actor_loader.py` builds a single `events(..., filterExpression: "<type/ability.id in (...)>")` per fight from all tracked spells, buffs and debuffs. It uses the `targetID` for buff and debuff events, subtracts `fight.start_time`, dedups on (spell, second, type), and pairs applies with removes in `process_auras`. `fight_phases.py` handles phases. Storage is S3 JSON keyed `spec/boss__difficulty__metric`, with loads fanned out through asyncio.gather. **Takeaway: one filtered `events` query per fight, with the ability list generated from the spell registry. That is exactly the quota trick paf needs.**

### Lorrgs frontend — github.com/gitarrg/lorrgs-frontend
- TypeScript, React 19, Redux, **Konva (canvas)**, Vite. Last push 2026-09-09. No license. Borrow the look (rows per player, colored cd bars with icons, boss-cast lane on top), not the code. For a local HTML report, a small SVG/Canvas renderer, or Plotly timeline bars, is enough.

### Talent string format (Blizzard) — verified from `Blizzard_ClassTalentImportExport.lua` (mirror github.com/Gethe/wow-ui-source)
- Header: version 8 bits, specID 16 bits, tree hash 128 bits (may be zero-filled by 3rd parties).
- Then, **for every node of the tree in ascending nodeID order** (`C_Traits.GetTreeNodes`): `selected` (1 bit). If selected, `purchased` (1). If purchased, `partiallyRanked` (1), then `ranks` (6) if partial, then `isChoice` (1), then `choiceIndex` (2, zero-based).
- Encoding is a base64 alphabet with an LSB-first bit order, so it is **not standard base64**: reading it with a standard decoder gives garbage.
- Node list from wago.tools, **verified CSV endpoints**: `https://wago.tools/db2/<Table>/csv` (optional `?build=`). The useful tables are TraitNode (`ID,TraitTreeID,PosX,PosY,Type,Flags,TraitSubTreeID`), TraitNodeEntry (`ID,TraitDefinitionID,MaxRanks,NodeEntryType,TraitSubTreeID`), TraitNodeXTraitNodeEntry (`TraitNodeID,TraitNodeEntryID,_Index`, where the choice index is `_Index`), TraitSubTree (hero trees), TraitDefinition, and SpellName.
- **Python code to reuse**: `encode_talent_string.py` in github.com/RPGLogs/mplus.subcreation.net (**MIT**, Python, last push 2024-01). It is an encoder with the **old v1 layout (no `purchased` bit)**, so patch it to v2. Nobody publishes a maintained Python decoder that I could find. Plan ~150 lines of our own code (encode+decode), with round-trip tests against strings exported in game and against simc (simc accepts `talents=<string>` natively; its C++ decoder is the reference **(unverified path, likely `engine/player/player.cpp`)**).
- WCL side: combatant info carries a `talentTree` list of `{id: TraitNodeEntryID, nodeID, rank}` **(unverified field names; check on one report)**. Mapping entry to node to choice index lets paf rebuild each top player's import string for R6.

### wago.tools DB2 (verified)
- JournalEncounter (`ID, JournalInstanceID, DungeonEncounterID, ...`) links the journal to the WCL encounterID (DungeonEncounterID = 3492 for Ula'tek, the same as Lorrgs/BigWigs). JournalEncounterSection (`JournalEncounterID, ParentSectionID, Type, SpellID, DifficultyMask, BodyText_lang`) gives the mechanic catalogue for Part 3. JournalSectionXDifficulty exists too **(unverified)**.

## 2. LEARN FROM

- **WoWAnalyzer** — github.com/WoWAnalyzer/WoWAnalyzer, TS/React, **AGPL-3.0** (copying code would make paf AGPL), active `midnight` branch. Elemental is marked compatible with **12.1.0**. Relevant files are under `src/analysis/retail/shaman/elemental/`. `modules/Abilities.tsx` gives cd rules per talent: Ascendance 180 s (120 with First Ascendant), Stormkeeper 60 s (lower with Herald/Rolling Thunder), Ancestral Swiftness 30 s off-GCD. Normalizers (`ElementalPrepullNormalizer`, `EventLinkNormalizer`, `EventOrderNormalizer`) show the log quirks to fix: prepull casts, cast/buff linking, and event ordering. The project refuses AI-generated contributions. Read it for **facts** (IDs, cd modifiers, which buff marks which cast), don't copy it.
- **BigWigs** — github.com/BigWigsMods/BigWigs, Lua, pushed 2026-09-27, **no license file**. `TheVenomousAbyss/Ulatek.lua` has the enable mob 257758, encounter 3492, option spell IDs per stage (S1/S2/intermission/S3), and the stage-transition triggers (`UNIT_TARGETABLE_CHANGED`). **Important Midnight change: timers are no longer hard-coded.** They come from Blizzard's `ENCOUNTER_TIMELINE_EVENT_ADDED`, so BigWigs **no longer holds a timer table** we could mine. It is useful for stage structure and names only. Its spell IDs differ from Lorrgs' WCL cast IDs (Caustic Waves 1292188 vs 1311807). Always take the ability IDs **from WCL events** and use BigWigs/Journal for labels.
- **pybots** — github.com/scatari69/pybots, **Apache-2.0**, Python/FastAPI, pushed 2026-07-23. Good for the simc job runner and the wago.tools item catalogue (R4). Its weapon-profileset segfault note is worth keeping in mind.
- **Subcreation** (MIT, dormant since 2024): shows how to aggregate a corpus into "X % of tops use talent Y". Methodology only.
- **sd_wcl** — github.com/xiaosongz/sd_wcl, notebooks, no license, 2026-03. Parses a local combat log into DuckDB and compares it with WCL tops. The DuckDB idea is worth a look against SQLite for T1b analytics.
- **wowarenalogs** — github.com/wowarenalogs/wowarenalogs, TypeScript, active, custom "Other" license. Its local WoWCombatLog parser matters only if paf later reads the user's own log file for x/y positions without WCL.

## 3. IGNORE

- **Archon.gg** is owned by Warcraft Logs and closed. **Murlok.io** is Go with a closed site (only a wiki repo). **Viserio/wowutils, raidplan.io and the MRT/NSRT note generators** are closed. The MRT note text format is trivial to parse ourselves: `{time:m:ss}` plus names and `{spell:id}` **(format from memory, verify on a real note)**.
- **WCL Python clients** (perdy/warcraftlogs, K0bus/warcraftlog-api-v2, aluiziolira/...) are small or stale, and paf's S2 client is already done. For the schema, run an introspection query with our own token and commit `schema.graphql`. No maintained public dump was found.
- **AutoSimC** is old combinatorial profile generation, and paf's Top Gear logic already goes further.

## Recommended actions (priority order)
1. T1/T2: copy the Lorrgs pattern (spell registry, one `events` query per fight with a generated `filterExpression`, relative timestamps, aura pairing). Write our own YAML registry for Elemental plus externals, seeded from WoWAnalyzer facts and Lorrgs IDs (after asking gitarrg or re-deriving the data from WCL).
2. T2/R6: build a `talents.py` encoder/decoder against the wago Trait* CSVs with v2 bits, then round-trip it through simc.
3. P-part: build the mechanic catalogue from JournalEncounterSection. Boss-cast IDs come from WCL events, and BigWigs gives only stage names and transitions.

## Not verified
- The WCL `talentTree` field names.
- The simc decoder file path.
- Whether the current serialization version is still 2 in 12.1. Check `C_Traits.GetLoadoutSerializationVersion()` or the header byte of a fresh export.
- The Lorrgs ranking query's exact field list (only its arguments were seen).
- Wowarenalogs' exact license terms.
- Whether any maintained Python talent decoder exists outside GitHub search reach.

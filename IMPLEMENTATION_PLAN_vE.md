# Mr Aura vE: Implementation Plan

Fixes for the weaknesses found in the 50 server games played by **Mr Aura vD** (submission 16309,
4 Oct 2026, 25 W / 25 L). The codebase is the C++ bot (`Mr_Aura_d_v2.zip`: `policy.hpp`,
`world.hpp`, `main.cpp`, `common.hpp`, `nav.hpp`, `board.hpp`, `io.hpp`).

Phases are ordered by expected gain per unit of work. Each phase is a separate submission, so
its effect can be measured on its own.

---

## Evidence summary (what we are fixing)

| # | Weakness | Evidence (50 server games) |
|---|----------|----------------------------|
| W1 | We don't take territory | Map covered in rounds 0–149: us ~35% in wins and losses alike; opponents 59% in our losses. Pearl-spawn tiles visited in losses: us 36%, them 73%. We covered less than the opponent in 22/25 losses. |
| W2 | Slow early economy | By round 100 (even in wins): pearls 24 vs 64, splits 11 vs 30. Dragons us ÷ them in losses: 0.53 at r50, 0.33 at r100. Median turning point: round 60. |
| W3 | Self-inflicted deaths | 58% of our deaths are walls, ourselves or teammates (opponents 36%). 1,249 wall deaths, only 23 with a free neighbour (boxed in). 483 crashes into a teammate's body. |
| W4 | Feeding and tiebreak | 831 deliberate feeding suicides from round 350, 387 of them after our queen was already dead. We lost three round-500 games while far ahead on dragons and total length, on the longest-dragon tiebreak (20 vs 24, 20 vs 63, 12 vs 13). |
| W5 | Queen | Median max length 4; 70 queen splits. Died in 12/25 losses (median round 124), mostly head-on, with ~3 enemies and 0 teammates within 3 tiles. In wins, 3 of 5 queen deaths were crashes into our own bodies. Queen survival alone won ≥4 games. |
| W6 | Corridor and multi-zone maps (repeating scenario) | Autarky 0–6: our heads stayed in the left third while the opponent held the middle and right. Stripes: 2–9 pearls eaten in losses; the queen orbited a 2×2 square beside the richest strip. weakhold: 5 and 38 pearls in losses. |
| W7 | Aggressive traders | Cognoscenti 0–5: 67% of their deaths are head-on trades; they win by numbers. |

**Round-500 tiebreak order:** (1) queen length, where a dead queen counts 0; (2) longest single
dragon; (3) total length. 28 of the 50 games went to round 500.

---

## Phase 0: Test infrastructure (do this first)

Every result so far has been limited by the test setup, not the bot. Fix that before changing
behaviour.

1. **Upgrade the local engine.** `unswbc` 0.3.6 rejects `SONAR <dir> <value>` and `PROTOCOL 3`,
   while the server supports them, so every local game has run with the radio off. Check that a
   newer release supports Protocol 3, then run `uv tool upgrade unswbc` or `pip install -U unswbc`.
   Confirm with a local replay: the engine log should show no `can't read line: SONAR`.
2. **Download the ladder maps.** `GET /api/v1/maps` returns every map in play, with its text.
   Save them all to `maps/` (Autarky, Stripes, Around UNSW, weakhold, Portals, Maze, Islands,
   Devil, Trauma, Prisoners Dilemma, Slithery Fight, Tower Defense, Australia and the rest).
3. **Move the tools into the repo** (`tools/`). They currently live in the session scratchpad:
   - `replay_decode.py`: replay decoder (packed Cap'n Proto, gzip for server copies).
   - `replay_analyse.py`: body reconstruction and per-game statistics (0 drift on 884,918 checks).
   - `territory.py`, `summarise.py`, `deaths2.py`: aggregate reports.
   - `harness.py`, `mkvar.py`, `mirror.py`: local match runners and variant builder.
   - `bcfetch.py`: downloads a submission's server replays via the API.
4. **Test-build rules** (learnt the hard way):
   - A small `BC_TURN_BUDGET` must come with a proportionally small `leanMargin`. Otherwise
     every turn is a one-step "lean" turn (no lookahead), and the test is invalid.
   - Per-game private copies of each bot, so parallel builds don't collide.
5. **Measurement protocol.** 16 games carry about ±3 wins of noise.
   - **Local:** a new version against vD, every ladder map, both sides, 3 runs each (~100+ games),
     with the metrics below. A change ships only if it beats vD by more than the noise **and**
     moves its target metric.
   - **Server:** after each upload, fetch its games with `bcfetch.py` and run the same reports.
     Ladder opponents are the real test.
6. **Report card per version.** These are the metrics from the analysis; keep them comparable
   between versions:
   - win rate overall and per map;
   - map coverage and spawn tiles visited (rounds 0–149);
   - pearls and splits by rounds 25, 50 and 100;
   - dragons us ÷ them at rounds 50, 100 and 200;
   - deaths by cause, and the share of self-inflicted deaths with a free neighbour;
   - queen survival, death round and cause;
   - feeding suicides;
   - tiebreak outcomes in round-500 games.

**Done when:** the upgraded local engine accepts our sonar, all ladder maps are local, and one
baseline report card for vD exists on local games.

---

## Phase 1: Tiebreak awareness and a single anchor (W4)

**Why first:** small code change, and it directly converts the round-500 games we already win
on numbers.

### Design
- Add a **tiebreak state** that every dragon can compute from shared facts each turn from round
  `tiebreakRound` (~300):
  - `ourQueenAlive`, plus the queen's length if visible;
  - `theirQueenAlive`, from the last sighting of enemy ID 0 or 1 and whether its death was seen
    (track sightings in `World`);
  - `ourLongest`, the longest teammate seen recently (radio-shared, below);
  - `theirLongest`, the longest enemy seen recently.
- **Anchor:** our queen if she's alive; otherwise our longest dragon (lowest ID breaks ties).
  - Each dragon broadcasts its length in a new packet, `PKT_STATUS` (ID, length, round), so
    everyone agrees who the anchor is.
  - The anchor never splits, never trades, uses queen-level danger weights, and is the only
    dragon that gets fed.
- **Feeding rules (replace the current block in `Policy::decide`):**
  - Only feed the anchor, never "the lowest-ID teammate below my ID".
  - Only when the anchor is in view, its path is predictable (feed spot = `feedAhead` tiles
    along its facing, a free tile), no enemy head is within `feedEnemyDist`, and
    `feedMaxLen` ≥ our length.
  - **Only when it changes the tiebreak:** we're behind or level on (queen, longest), or the
    margin is small. If we're comfortably ahead, don't feed; play safe.
  - One feeder at a time (`amFeeder`, already in place).
- **No new splits after `tiebreakRound`**, except the "boxed in" reverse split as a last resort.
- From `tiebreakRound`, non-anchor dragons with a big lead in total length switch to
  **protecting** the anchor: escort ring 4–6, intercept enemies within its reach.

### Code changes
- `world.hpp`: enemy-queen sighting and death tracking; a recent-lengths table (own and enemy);
  receive `PKT_STATUS`.
- `main.cpp`: send `PKT_STATUS` on one ray (alternating with the existing packets); remove the
  "late game override" block's feeding changes (`feedRound = lateGameRound`).
- `policy.hpp`: `tiebreakState()`, `anchorId()`; rewrite the feeding block; gate `trySplit`
  and `queenSplit` on `round < tiebreakRound`.
- `common.hpp`: `tiebreakRound`, `feedEnemyDist`, `feedOnlyIfBehind`, `anchorEscortRing`.

### Acceptance
- Feeding suicides drop from ~17 per game to only those that grow the anchor. Measure:
  anchor length before and 10 rounds after each feed.
- No feeding while our queen is dead and no anchor is in view.
- In round-500 games: our longest ≥ their longest in the majority of games we lead on total
  length.
- Win rate against vD on round-500 games improves; elimination results are unchanged.

---

## Phase 2: Queen survival (W5)

### Design
- **Stop queen splitting after the opening:** set `queenSplitUntil` to ~60 (the first army),
  and add a minimum queen length after the opening (`queenKeepLen`).
- **Enemy threat field instead of only "adjacent to an enemy head":**
  - For every visible enemy head, compute its reach (`reachOf(len)` with its free steps).
  - The queen's move score subtracts danger for any destination inside the reach of one enemy,
    scaled up when two or more enemies can reach it.
  - Prefer moves that keep **more escape room** (flood size) than the nearest enemy can cut off.
- **Flee early:** if 2 or more enemy heads are within `queenAlarmRadius` (~5), the queen's top
  priority is to increase her distance from the enemy centre of mass, through known safe space
  (portals only with a good report).
- **Escorts:** 1–2 escorts hold a ring of 4–5 around the queen and intercept enemies inside
  `queenThreatRadius`. Already partly built (`escortCount`, `escortRing`, threat hunts): retune
  rather than add.
- **No friendly crowding:** keep the personal-space penalty and the queen-room check; add a
  hard rule that no teammate may end a move on one of the queen's 4 neighbour tiles unless
  defending. (A strong penalty, not illegal, so a trapped teammate still has a fallback.)

### Code changes
- `policy.hpp`: queen danger in `scoreFrom` (sprint reach for every enemy, multi-enemy scaling),
  a flee mode in `decide` for `queen_`, `queenSplit` gating.
- `common.hpp`: `queenSplitUntil`, `queenKeepLen`, `queenAlarmRadius`, `wQueenReach`,
  `wQueenMulti`.

### Acceptance
- Queen survives to round 500 in ≥60% of local games against vD (vD: ~30% on the server).
- Queen deaths by our own bodies: 0 in the test set.
- Median queen max length ≥ 8 (vD: 4).
- No loss in early economy (Phase 4 metrics at round 100 within noise of vD).

---

## Phase 3: Territory and dispersion (W1), including corridor maps (W6)

The biggest single cause of losses. This is the largest phase, so build it in steps 3a–3d and
measure after each.

### 3a. Region values instead of single-tile exploration
- Divide the board into **regions**: fixed 8×8 blocks on open maps; on walled maps, connected
  components separated by chokepoints (3b).
- Region value = known pearl beds × expected refill + unseen tiles × explore value +
  staleness (rounds since any teammate saw it) − claim (teammates heading there).
- Each dragon picks a **target region** (best value ÷ path distance) and keeps it for several
  turns. That commitment breaks orbits and stops dithering. `scoreFrom` gets a pull toward the
  region's entrance, using `gammaFar`.
- Replace the current single-tile `exploreTarget` (`maybeStartExplore`) with this; keep the
  revisit penalty.

### 3b. Chokepoints, zones and gateways
- At start-up, and whenever kelp knowledge changes, compute **zones**: flood fill the known
  board, treating 1–4-wide gaps between kelp runs as boundaries (narrow cuts in the passable
  graph). Portals join zones.
- A **gateway** is a gap or portal between zones. Crossing one into a zone with high value and
  low claim gets a bonus. Portal reports (already built) feed the zone's value.
- **This fixes the Autarky and Stripes pattern:** dragons see "the middle zone holds 40% of the
  beds and nobody of ours is there" and go.

### 3c. Dispersion
- Each dragon broadcasts its target region (`PKT_CLAIM`: region ID, dragon ID, round).
- A region claimed by k teammates has its value divided by (1 + k). This replaces the current
  closest-teammate pearl discount as the main spreading force.
- At game start, starting dragons sort themselves to different regions by ID, so the opening
  spreads instead of clumping.

### 3d. Orbit breaker for corridors
- On maps with corridors (passable width ≤ 3 over long runs), a dragon that hasn't eaten for N
  turns and is in a low-value region must commit to the best gateway, overriding the local
  forage pull until it's through.

### Code changes
- New `zones.hpp`: zone and gateway computation over `Board` (cached, rebuilt on terrain
  change), plus region values.
- `world.hpp`: per-region "last seen by us" round (from own vision and radio); claim table.
- `main.cpp`: `PKT_CLAIM` send and receive.
- `policy.hpp`: target-region selection in `decide`; a region pull term and gateway bonus in
  `scoreFrom`; remove or retire `maybeStartExplore`.
- `common.hpp`: region size, weights, claim divisor, corridor thresholds.

### Acceptance
- Map coverage (rounds 0–149) ≥ 50% on the ladder maps; spawn tiles visited ≥ 60%.
- On Autarky, Stripes and weakhold: our heads present in every zone by round 100 in most games.
  Pearls eaten within 2× of the opponent's (vD: 10× behind).
- Orbit rate ≤ 3%, and no orbit longer than 8 turns.
- Win rate on the multi-zone maps above vD's, beyond the noise.

---

## Phase 4: Faster, safer opening (W2)

### Design
- **Opening phase** (rounds 0–~100, `openingEnd`): the objective is pearls and dragon count.
  - Head-on trades only when we're clearly longer (by `openingTradeMargin` ≥ 2) or have local
    superiority. No even trades: early segments compound.
  - Split as soon as both halves have room. Halves of at least 2–3 that immediately head for
    different regions (from Phase 3).
  - No hunting or escort jobs except defending the queen.
- **Split pacing by economy:** split when our recent pearl rate supports two foragers (room and
  pearls in the target regions), not on length alone.
- Keep the army cap off (it lost badly in testing).

### Code changes
- `policy.hpp`: an `opening()` phase flag; gate `tradeOk`, `sprintTrade` and `buildSquadTargets`
  on it; split-room checks use region value.
- `common.hpp`: `openingEnd`, `openingTradeMargin`.

### Acceptance
- By round 100: pearls ≥ 0.8× the opponent's and splits ≥ 0.8× (vD: 0.4× and 0.37×).
- Dragons us ÷ them at round 50 ≥ 0.9 in losses (vD: 0.53).
- Early head-on deaths (rounds 0–100) down at least 30% against vD.

---

## Phase 5: Trap and congestion avoidance (W3)

### Design
- **Deeper trap check:** the space check uses `nav_.flood` from the destination. Add a check
  along the route: when entering a corridor or pocket, the remaining exits must still give room
  ≥ length after `k` steps, counting the bodies of teammates heading the same way.
- **Corridor reservation:** a dragon entering a 1-wide corridor broadcasts it (or the corridor
  is claimed by ID order). Others don't enter from the other end while it's occupied. This
  removes most crashes into teammates.
- **Wall deaths are traps, so stop entering pockets late.** The pocket penalty (`wPocket`)
  applies only on the first step. Extend it to a "dead-end depth" penalty: the number of tiles
  you can go in before the only way out is back.

### Code changes
- `nav.hpp`: dead-end depth helper (BFS from the destination with the time-aware body).
- `policy.hpp`: route-aware space check in `scoreFrom`; corridor reservation.
- `world.hpp` and `main.cpp`: corridor claim packet (or reuse `PKT_CLAIM`).

### Acceptance
- Self-inflicted deaths ≤ 40% of our deaths (vD: 58%; opponents: 36%).
- Wall deaths per 100 dragons created down 50% against vD.
- Crashes into teammates' bodies down 50%.

---

## Phase 6: Opponent-adaptive trading (W7)

### Design
- Track, per game, the share of enemy deaths that are head-on trades, and how often enemies
  move toward our heads (from vision).
- Against **high-trade opponents** (Cognoscenti-like, ≥50% head-on): raise `tradeSlack` against
  us, demand local superiority for every trade, and keep dragons in pairs so a trade is
  followed by our pickup of the drops.
- Against **sloppy expanders** (shark++-like, high self-death rate, high coverage): play
  territory (Phase 3) and let them self-destruct; avoid early trades.

### Code changes
- `world.hpp`: running opponent style counters (from vision: enemy heads adjacent to ours,
  enemy deaths seen).
- `policy.hpp`: adjust trade parameters from the style counters.

### Acceptance
- Against Cognoscenti and shark++ (ladder): any wins; locally, a trade-heavy variant of vD as a
  sparring partner.

---

## Release plan

| Version | Contents | Ship check (local, against vD) | Then on the server |
|---------|----------|------------------------------|---------------------|
| vE1 | Phase 0 + Phase 1 | Round-500 wins up; nothing else worse | Fetch games, report card |
| vE2 | + Phase 2 | Queen survival ≥ 60% | Report card |
| vE3a–d | + Phase 3 steps | Coverage, multi-zone maps | Report card per step |
| vE4 | + Phase 4 | Early economy ratios | Report card |
| vE5 | + Phase 5 | Self-inflicted ≤ 40% | Report card |
| vE6 | + Phase 6 | Against trade-heavy sparring | Watch Cognoscenti and shark++ games |

**Rules:**
- One phase per submission.
- Keep every new behaviour behind a `Params` value, so it can be turned off without code changes.
- Never ship a change that loses to vD beyond noise, even if its target metric improves. The
  first round of changes showed how easily a "fix" can starve the army (0/16).

---

## Risks

- **Splitting is the economy.** Every earlier attempt to reduce splitting lost almost every
  game. Phases 2 and 4 restrict *where* and *who* splits, not *how much*. Watch dragon counts
  in every test.
- **The radio is shared and lossy.** Sonar stops at the first dragon and carries no sender. New
  packets (`PKT_STATUS`, `PKT_CLAIM`) must tolerate missing or old data, and everything must
  still work with no radio at all.
- **CPU.** Zone computation and extra floods must fit the per-turn budget. Cache zones and
  rebuild them only when terrain knowledge changes. Measure turn times in the logs (`ms=`).
- **Local isn't the server.** Opponents on the ladder differ from vD mirrors. The server report
  card is the final word.

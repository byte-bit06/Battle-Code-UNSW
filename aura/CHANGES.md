# Changes in vE1 (from vD, submission 16309)

Plan: `IMPLEMENTATION_PLAN_vE.md`, Phase 1 (tiebreak awareness and a single anchor).

Why: in vD's 104 server games, 59 went to round 500, where the order is queen length, then
longest dragon, then total length. vD lost 11 of them while ahead on total length, and its
dragons fed themselves to whoever had a lower id: 18 suicides a game, many after our queen
was dead.

- **Anchor**: our queen while she is known alive, otherwise our longest dragon (lowest id on
  ties). Every dragon computes it from the same facts (`World::anchorId`).
- **Status radio** (`PKT_STATUS`): every dragon broadcasts its id and length on one ray; the
  queen's sonar ping carries hers (the echo works whatever the value).
- **Feeding**: only the anchor is fed, only when it is in view, only with no enemy head within
  `feedEnemyDist` of the drop spot, and only while the anchor is not already ahead of the
  rival (enemy queen if seen, else their longest seen) by more than `feedLead`. Feeding starts
  at `feedRound` (400); the late-game override that started it at 350 is gone.
- **From `tiebreakRound` (300)**: no splits (the boxed-in escape split stays); the anchor never
  trades and uses queen-level danger; escorts hold `anchorEscortRing` around the anchor.

# Changes in vE2 (Phase 2: queen survival)

Why: in vD's server games the queen never grew (median max length 4, 191 queen splits), died
in 20 of 56 losses (median round 162), mostly head-on with ~3 enemies and no teammate within
3 tiles, and 3 of her deaths in wins were crashes into our own bodies. Her survival alone
decided several round-500 games.

- **Queen splits only in the opening**: `queenSplitUntil` 500 -> 60, and a queen split always
  leaves her at least `queenKeepLen` (4).
- **Enemy reach field**: for each move the queen pays `wQueenReach` per enemy head that can
  reach the tile this round, plus `wQueenMulti` per additional one.
- **Flee mode**: with 2+ enemy heads within `queenAlarmRadius` (5), tiles further from them
  are worth `wQueenFlee`; she may cross a known portal only if a teammate reported it good.
- **Escape room**: the queen values reachable space (`wQueenRoom`) on top of `wSpace`.
- **Escorts**: 2 (was 3), ring 4 (was 3).
- **No crowding**: `wQueenAdjacent` penalty for a teammate ending on one of the queen's four
  neighbour tiles unless defending (a penalty, not illegal, so a trapped teammate can still
  get out).

# Changes in vE3 (Phase 3: territory and dispersion)

Why: vD's heads covered ~35% of the map in rounds 0-149 whatever the result; in losses the
opponent covered 45-59% and visited 64% of the pearl-spawn tiles to our 38%. On corridor and
multi-zone maps (Autarky, Stripes, weakhold) our dragons stayed in their starting zone.

- **Regions (3a, `regions.hpp`)**: 8x8 blocks, each split into its connected parts, so every
  region is one connected area (on Stripes each corridor piece is its own region). Region
  value = pearls believed there + known beds (hot beds weigh more) + share never seen +
  staleness. Each dragon commits to a target region for `regionCommit` rounds (or until it
  is there and the value has dropped below `regionDone`), and a terrain path field pulls it
  there (`wRegion`, `regionGamma`). The old single-tile explore mode is retired; looping now
  means "commit to a different region". The revisit penalty stays.
- **Gateways (3b)**: the path field follows gaps and known portals, so the way into another
  zone goes through its gateways; portal reports still score each crossing. (No separate
  zone graph: the connected regions plus the field do that job.)
- **Dispersion (3c)**: `PKT_CLAIM` broadcasts each dragon's target (as a tile, since region ids
  depend on each dragon's own map knowledge) on odd rounds, on the ray that carries the status
  on even rounds. A region's value is divided by 1 + the number of teammates claiming it. In
  the first `openingSpreadRounds` the k-th lowest-id teammate nearby takes the k-th best region.
- **Orbit breaker (3d)**: no pearl for `hungryTurns` (25) forces a new target outside the
  current region, with the pull multiplied by `hungryBoost` until we get there.

# Changes in vE4 (Phase 4: faster, safer opening)

Why: by round 100 vD had eaten 30 pearls to the opponent's 60 and split 15 times to their 28
(even in wins: 44 vs 48); 40-49% of our deaths were head-on trades, many of them early.

- **Opening** (`openingEnd`, rounds 0-99): head-on trades only against an enemy at least
  `openingTradeMargin` (2) longer than us. A head-on kills both, so an even trade just throws
  away early segments. This one rule (`tradeOk`) also covers the kamikaze pulls and sprint
  trades. Defending the queen is still always allowed.
- **No hunting in the opening** except against enemies threatening our queen (escorting only
  starts at `earlyEnd`, 120, anyway).
- **Split pacing by economy**: a normal split (swarm or bud) also needs a pearl within the last
  `hungryTurns`, and at least two regions within `splitRegionDist` worth `splitRegionValue`
  after teammates' claims, one for each half. Deliberately lenient: unexplored regions pass
  easily, and every hard cut to splitting lost to vD in testing. Queen and tactical splits
  are unchanged.
- The army cap stays off.

# Changes in vE5 (Phase 5: traps and congestion)

Why: 60% of vD's deaths on the server were self-inflicted (opponents 36%). The 2402 wall
deaths almost never had a free neighbour, so they were dead ends walked into rather than
misjudged steps; another 1208 were crashes into bodies, mostly teammates' (~11 a game).

- **Dead-end depth** (`deadEndDepth` in `nav.hpp`): from the destination, walk on while there
  is exactly one way forward. If that ends with no way on, the move pays `wDeadEnd` per tile of
  depth (up to `deadEndCap`). Our own body is timed, so a tail that will have moved away is
  not a wall. This extends the old one-step pocket check, which only saw dead ends of depth 1.
- **Corridors** (`Corridors` in `regions.hpp`): chains of at least `corridorMinLen` tiles with
  at most two ways on, found from the terrain and rebuilt when it changes. A corridor's id is
  its lowest tile, so dragons with the same map knowledge agree on it.
- **Corridor reservation** (`PKT_CORRIDOR`): a dragon inside a corridor reserves it on one ray
  every turn. Entering a corridor that a teammate reserved in the last `corridorMemory` rounds,
  or that a teammate's head is visibly in, costs `wCorridorBusy`, so two of ours don't meet
  inside it from opposite ends.

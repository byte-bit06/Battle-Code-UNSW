# Changes from submission 15946

## Circling, blocked-off pearls, portals
- Space check is a sliding penalty: only a move with less room than our own length is
  vetoed. Tight spaces cost `wCramped`, and their pearls still count (they used to be
  thrown away, so pockets with pearls were never entered).
- Other dragons' bodies are timed like our own when the whole body is in view: their
  segments free up as they move instead of being permanent walls.
- Anti-loop memory: the last `recentMemory` head tiles. Stepping back onto them costs
  `wRevisit`; standing on one tile `loopHits` times starts explore mode (head for the
  nearest stale or unseen tile for `exploreTurns` rounds).
- Tiles not seen for `staleAge` rounds are worth re-exploring (`staleValue`).
- A closer teammate shrinks a pearl's value (`claimNear` / `claimFar`) instead of zeroing it.
- Ties break toward the current heading, then a per-dragon order (they always went North).
- Unknown portals: one scout (the lowest-id non-queen dragon nearby), valued by
  `wScout - scoutLenCost * length`, instead of a flat 3.0 for everyone.
- Portal reports: after crossing, the scout broadcasts what it found on the far side
  (pearls, room, enemy heads) for `reportTurns` rounds. Teammates store a score per
  portal and add it when crossing; a bad report keeps everyone out. A teammate that
  vanishes into a portal with no report within `reportWait` rounds counts as bad.
- Every radio packet carries a team signature; unsigned or enemy packets are ignored.
- `-1` body cells (after crossing a blind portal) are skipped in `markBody`.

## Splitting and crowding around the queen
- Teammates pay `wQueenSpace` for ending within `queenSpaceRadius` of the queen, and
  `wQueenBox` for a move that shrinks her reachable room below what she needs.
- Feeding: one feeder at a time, dying `feedAhead` tiles ahead of the target's facing
  (never beside its head); the late-game `feedMaxLen = 15` override is gone (default 6).
- "Outnumbered: unlimited splitting" needs `outnumberedTurns` turns in a row.
- The queen's splitting has its own rule (`queenSplitUntil`, `queenSplitMinLen`,
  `queenCrowdRadius`, `queenReverse`); the queen never plans a pocket entry it can only
  leave by splitting.
- New split limits exist but are off by default (`splitQueenDist`, `unitsPerTiles`):
  in testing, every setting that cut splitting lost to the old bot.

## Testing (local, 8 maps x both sides, against submission 15946)
- This version: 9/16. Submission 15946 against itself: 9/16. Level within noise.
- Queen never splits / splits only early, army capped, no splits near the queen: 0-1/16.

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

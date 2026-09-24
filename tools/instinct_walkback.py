"""How early was the box avoidable? (Instinct_Engine)

Every death in the scripted ladder is a box: by the time anything flags danger,
no move helps. So the question is not "was the fatal move wrong" but "when was
the last turn a better-connected move existed, and did we take it".

For each losing run this replays the game and, every turn, scores each legal
move by the corridor count of the board it leads to (counted to the joint
envelope frontier - the signal the engine steers on). It then reports the last
turn where an alternative beat the move we took, and how many rounds before
death that was.

    python tools/instinct_walkback.py --seeds 4

Read it like this: if that distance is typically 5+ rounds, a standing corridor
cost at L1 can fix these deaths. If it is 1-2, the box was already built and
the cause is upstream of Instinct.
"""
import argparse
import os
import statistics
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "arena"))
sys.path.insert(0, os.path.join(ROOT, "mybot"))

import instinct_arena as ia   # noqa: E402
from instinct import control, corridors, policy   # noqa: E402
from instinct.state import TIER_A   # noqa: E402

HORIZON = 6
TRACE = []


def instrument():
    """Score every legal move by where it leads, then let the engine choose."""
    orig = ia.Defender.act

    def act(self, sim, d):
        st = self.state(sim, d)
        ctrl = control.build_control(st, horizon=HORIZON)
        frontier = ctrl.free_frontier(HORIZON) if st.enemies else None
        scores = {}
        for mv in policy.legal_moves(st):
            nxt = policy.after_move(st, [mv], TIER_A)
            if nxt is None:
                continue
            scores[mv] = corridors.corridor_count(nxt, open_set=frontier)
        out = orig(self, sim, d)
        taken = out[0][1][0] if out[0][0] == "move" else None
        TRACE.append((sim.round, taken, scores))
        return out

    ia.Defender.act = act


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=4)
    ap.add_argument("--rounds", type=int, default=150)
    a = ap.parse_args()

    losses = []
    for name in sorted(ia.LADDER):
        for first in (True, False):
            for seed in range(a.seeds):
                r = ia.run(name, first, a.rounds, seed=seed)
                if r is not None and r["cause"] != "survived":
                    losses.append((name, first, seed, r))
    print(f"{len(losses)} losing runs; replaying each with per-move corridor scoring\n")

    instrument()
    gaps = []
    print(f"{'scenario':22s} {'death':>5s} {'cause':>12s} {'last better alt':>15s} "
          f"{'rounds before death':>19s}")
    for name, first, seed, r in losses:
        TRACE.clear()
        ia.run(name, first, a.rounds, seed=seed)
        last = None
        for rnd, taken, scores in TRACE:
            if taken is None or taken not in scores:
                continue
            best = max(scores.values())
            if best > scores[taken]:
                last = (rnd, scores[taken], best)
        label = f"{name} {'att-first' if first else 'we-first'} s{seed}"
        if last is None:
            print(f"{label:22s} {r['rounds']:5d} {r['cause']:>12s} {'never':>15s} {'-':>19s}")
            continue
        gap = r["rounds"] - last[0]
        gaps.append(gap)
        print(f"{label:22s} {r['rounds']:5d} {r['cause']:>12s} "
              f"{'r%d (%d->%d)' % (last[0], last[1], last[2]):>15s} {gap:>19d}")
    if gaps:
        gaps.sort()
        print(f"\nrounds between the last better-connected alternative and death:")
        print(f"  median {statistics.median(gaps):.0f}   min {gaps[0]}   max {gaps[-1]}   n={len(gaps)}")
        print(f"  5 or more: {sum(1 for g in gaps if g >= 5)}/{len(gaps)}")


if __name__ == "__main__":
    main()

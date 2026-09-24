"""Read the head-to-head deaths one at a time (they are 60% of our deaths).

For each lost run, the last three turns before the point of no return:
who killed us, its id relative to ours, its length, its distance, whether ram
exposure flagged it, whether an alternative move existed, and what the trade
rule said. Those separate three different bugs:

  chosen move's POST-MOVE exposure was 0, and a ram still killed us
        -> the reachability set is too small (a sprint or portal path we miss)
  exposure > 0 and no alternative had 0
        -> a real box: an upstream ranking problem, not 4.6
  exposure > 0 while a ram-free alternative existed
        -> the ranking or the trade rule let it happen

Exposure is measured on the tile we LAND on, not the one we start from: an
enemy two tiles away cannot reach our head, but can reach where we are going.

    python tools/instinct_deaths.py            # every scenario, both id orders
    python tools/instinct_deaths.py --seeds 4
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "arena"))
sys.path.insert(0, os.path.join(ROOT, "mybot"))

import instinct_arena as ia   # noqa: E402
from instinct import policy, tempo   # noqa: E402
from instinct.state import TIER_A, TIER_B   # noqa: E402

HISTORY = []


def patch():
    orig = ia.Defender.act

    def act(self, sim, d):
        st = self.state(sim, d)
        rams = tempo.ram_threats(st, st.head, TIER_A)
        legal = policy.legal_moves(st)
        safe_alts = []
        for mv in legal:
            nxt = policy.after_move(st, [mv])
            if nxt is not None and tempo.ram_exposure(nxt, nxt.head, TIER_A) == 0:
                safe_alts.append(mv)
        chosen = None
        orig_out = orig(self, sim, d)
        if orig_out[0][0] == "move":
            nxt = policy.after_move(st, orig_out[0][1])
            chosen = (orig_out[0][1],
                      tempo.ram_exposure(nxt, nxt.head, TIER_A) if nxt else None)
        HISTORY.append(dict(
            chosen=chosen,
            round=sim.round, head=d.head, my_id=d.id, my_len=d.length,
            enemies=[(e.id, e.length, st.geo.manhattan(st.head, e.head),
                      "earlier-id" if e.id < d.id else "later-id") for e in st.enemies],
            flagged=[e.id for e in rams],
            trade_ok=[e.id for e in st.enemies if policy.may_trade(st, e)],
            legal=legal, ram_free_alts=safe_alts))
        return orig_out

    ia.Defender.act = act
    return orig


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--rounds", type=int, default=150)
    a = ap.parse_args()
    patch()
    verdicts = {}
    for name in sorted(ia.LADDER):
        for first in (True, False):
            for seed in range(a.seeds):
                HISTORY.clear()
                r = ia.run(name, first, a.rounds, seed=seed)
                if r is None or r["cause"] == "survived":
                    continue
                print(f"\n=== {name} {'attackers-first' if first else 'we-move-first'} "
                      f"seed {seed}: {r['cause']} at round {r['rounds']}")
                tail = HISTORY[-3:]
                for h in tail:
                    print(f"  r{h['round']:3d} head={h['head']} L={h['my_len']} id={h['my_id']} "
                          f"legal={h['legal']} ram-free-alts={h['ram_free_alts']} "
                          f"chose={h['chosen'][0] if h['chosen'] else None} "
                          f"post-move-exposure={h['chosen'][1] if h['chosen'] else None}")
                    for eid, elen, dist, order in h["enemies"]:
                        print(f"        enemy {eid} ({order}) L={elen} dist={dist} "
                              f"flagged={'yes' if eid in h['flagged'] else 'NO '} "
                              f"trade-rule={'ACCEPTS' if eid in h['trade_ok'] else 'refuses'}")
                if tail:
                    last = tail[-1]
                    exposure = last["chosen"][1] if last["chosen"] else None
                    if r["cause"] == "head-to-head":
                        if exposure == 0:
                            v = "A: we landed on a tile we scored as ram-free (model gap)"
                        elif not last["ram_free_alts"]:
                            v = "B: exposed, and no ram-free alternative (a real box)"
                        else:
                            v = "C: exposed while a ram-free move existed (ranking/trade)"
                    elif not last["legal"]:
                        v = f"D: no legal move at all ({r['cause']}) - boxed in earlier"
                    else:
                        v = f"other: {r['cause']}"
                    print(f"  -> {v}")
                    verdicts[v] = verdicts.get(v, 0) + 1
    print("\nverdicts:", verdicts)


if __name__ == "__main__":
    main()

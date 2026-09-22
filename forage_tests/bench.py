"""Native timing benchmark for forage_turn on a crowded 64x64 board.

Native CPython is ~30-50x faster than the judge's metered interpreter, so this
is only a relative measure (use it to compare changes). The real check is:
    unswbc run --sandbox -v --no-replay maps/default.map mybot oldbot > run.txt 2>&1
    python forage_tests/sandbox_points.py run.txt
"""
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fakes import make, NoDeadline  # noqa: E402

import forage  # noqa: E402
import safety  # noqa: E402


def board(rng):
    W = H = 64
    me = [(30 - i, 30) for i in range(25)]
    others = [(90 + k, [(34 + k * 2, 26 + j) for j in range(8)], False) for k in range(3)]
    taken = set(me) | {c for _, cs, _ in others for c in cs}
    free = [(x, y) for x in range(20, 44) for y in range(20, 44) if (x, y) not in taken]
    pearls = rng.sample(free, 25)
    cds = {p: rng.randint(1, 12) for p in rng.sample(free, 200)}
    kelp = [(rng.randrange(20, 44), rng.randrange(20, 44), rng.randrange(4)) for _ in range(40)]
    return make(W, H, me, my_id=4, others=others, pearls=pearls, countdowns=cds,
                kelp=kelp, round_num=rng.randint(1, 499))


def main(runs=500):
    rng = random.Random(7)
    times = []
    for _ in range(runs):
        snap, mem = board(rng)
        safe = safety.get_safe_moves(snap, mem)
        t = time.perf_counter()
        forage.forage_turn(snap, mem, safe, NoDeadline())
        times.append(time.perf_counter() - t)
    times.sort()
    n = len(times)
    print(f"native forage_turn over {n} runs: p50 {times[n // 2] * 1e3:.2f} ms  "
          f"p95 {times[int(n * .95)] * 1e3:.2f} ms  max {times[-1] * 1e3:.2f} ms")
    print("multiply by ~30-50 for a rough judge estimate; confirm with sandbox_points.py")


if __name__ == "__main__":
    main()

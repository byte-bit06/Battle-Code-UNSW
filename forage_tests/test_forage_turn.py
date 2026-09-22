"""Stage 5 contract: always returns a list of ints whose first move is in safe."""
import random

import forage
import safety
from fakes import make, NoDeadline


def test_no_pearls_explores():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)])
    safe = safety.get_safe_moves(snap, mem)
    act = forage.forage_turn(snap, mem, safe, NoDeadline())
    assert len(act) == 1 and act[0] in safe


def test_goes_for_visible_pearl():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], pearls=[(8, 5)])
    safe = safety.get_safe_moves(snap, mem)
    assert forage.forage_turn(snap, mem, safe, NoDeadline()) == [1]


def test_empty_safe_returns_empty():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)])
    assert forage.forage_turn(snap, mem, [], NoDeadline()) == []


def _random_snake(rng, W, H, L, taken):
    x, y = rng.randrange(W), rng.randrange(H)
    cells = [(x, y)]
    if (x, y) in taken:
        return None
    for _ in range(L - 1):
        opts = []
        for dx, dy in ((0, 1), (1, 0), (0, -1), (-1, 0)):
            n = ((cells[-1][0] + dx) % W, (cells[-1][1] + dy) % H)
            if n not in cells and n not in taken:
                opts.append(n)
        if not opts:
            return None
        cells.append(rng.choice(opts))
    return cells


def test_stress_1000_random_boards():
    rng = random.Random(1234)
    done = 0
    while done < 1000:
        W, H = rng.randint(10, 24), rng.randint(10, 24)
        taken = set()
        me = _random_snake(rng, W, H, rng.randint(3, 20), taken)
        if me is None:
            continue
        taken |= set(me)
        others = []
        for k in range(rng.randint(0, 4)):
            s = _random_snake(rng, W, H, rng.randint(2, 12), taken)
            if s:
                taken |= set(s)
                others.append((rng.choice([1, 3, 50, 99]), s, rng.random() < 0.3))
        free = [(x, y) for x in range(W) for y in range(H) if (x, y) not in taken]
        pearls = rng.sample(free, min(len(free), rng.randint(0, 10)))
        kelp = [(rng.randrange(W), rng.randrange(H), rng.randrange(4)) for _ in range(rng.randint(0, 25))]
        cds = {p: rng.randint(-1, 12) for p in rng.sample(free, min(len(free), 30))}
        snap, mem = make(W, H, me, my_id=rng.choice([2, 7, 60]), others=others,
                         pearls=pearls, kelp=kelp, countdowns=cds,
                         round_num=rng.randint(1, 499))
        safe = safety.get_safe_moves(snap, mem)
        act = forage.forage_turn(snap, mem, safe, NoDeadline())
        assert act is not None and isinstance(act, list)
        if safe:
            assert act and all(isinstance(d, int) and 0 <= d <= 3 for d in act)
            assert act[0] in safe
        else:
            assert act == []
        done += 1

"""Spawn timing (engine-verified by probe_bot): a countdown T seen now spawns at
the start of round now+T and only if the tile is empty, so we must be ADJACENT
after move T and step on at move T+1."""
import config
import forage
import routing
from fakes import make, NoDeadline


def test_parity_makes_some_waits_impossible():
    # On a grid every move flips (x+y) parity. From distance 1, after an odd
    # number of moves we can never be adjacent to the target.
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], countdowns={(6, 5): 3})
    c = forage.make_ctx(snap, mem, [0, 1, 2], NoDeadline())
    assert forage.timed_approach(c, mem.geo.idx(6, 5), 3) is None


def test_timed_approach_T4():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], countdowns={(6, 5): 4})
    c = forage.make_ctx(snap, mem, [0, 1, 2], NoDeadline())
    g = mem.geo
    target = g.idx(6, 5)
    moves = forage.timed_approach(c, target, 4)
    assert moves is not None and len(moves) == 4 + config.SPAWN_EAT_OFFSET
    before = routing.simulate(g, snap.body, 3, moves[:4], set(), snap.walls)
    assert target not in before.body                   # tile empty at spawn time
    assert target in g.neighbours(before.body[0])      # adjacent, ready to strike
    after = routing.simulate(g, snap.body, 3, moves, set(), snap.walls)
    assert after.body[0] == target                     # eat on move T+1


def test_timed_approach_impossible_returns_none():
    # long dragon in a 1-wide corridor can't wait next to the target
    kelp = [(x, 5, 0) for x in range(0, 20)] + [(x, 5, 2) for x in range(0, 20)]
    body = [(5, 5), (4, 5), (3, 5), (2, 5), (1, 5), (0, 5)]
    snap, mem = make(20, 20, body, kelp=kelp, countdowns={(6, 5): 3})
    c = forage.make_ctx(snap, mem, [1], NoDeadline())
    assert forage.timed_approach(c, mem.geo.idx(6, 5), 3) is None

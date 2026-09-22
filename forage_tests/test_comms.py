"""Sonar protocol and teammate information."""
import comms
import config
import forage
import memory
import safety
from fakes import make, NoDeadline


def test_encode_decode_roundtrip():
    for kind in range(1, 7):
        for x, y, p in ((0, 0, 0), (63, 63, 255), (12, 40, 7)):
            v = comms.encode(kind, x, y, p)
            assert 0 <= v <= 0xFFFFFFFF
            assert comms.decode(v) == (kind, x, y, p)


def test_random_numbers_mostly_rejected():
    import random
    rng = random.Random(3)
    accepted = sum(1 for _ in range(20000) if comms.decode(rng.getrandbits(32)) is not None)
    assert accepted < 20000 * 0.01          # ~1/256 * 6/16 expected


def test_symmetry_report_locks_hypothesis():
    snap, mem = make(20, 12, [(1, 1), (1, 2), (1, 3)])
    c = comms.Comms()
    c.receive([comms.encode(comms.T_SYM, 0, 0, comms.SYM_CODE["R"])], snap, mem)
    assert mem.sym.locked() == "R"


def test_symmetry_report_ignored_if_we_disproved_it():
    snap, mem = make(20, 12, [(1, 1), (1, 2), (1, 3)])
    mem.sym.alive["R"] = False
    comms.Comms().receive([comms.encode(comms.T_SYM, 0, 0, 3)], snap, mem)
    assert mem.sym.locked() is None and not mem.sym.alive["R"]


def test_claim_makes_us_yield():
    snap, mem = make(30, 30, [(5, 5), (4, 5), (3, 5)], pearls=[(9, 5)])
    comms.Comms().receive([comms.encode(comms.T_CLAIM, 9, 5, 2)], snap, mem)   # teammate 2 away
    c = forage.make_ctx(snap, mem, safety.get_safe_moves(snap, mem), NoDeadline())
    cand = forage.Candidate(mem.geo.idx(9, 5), "live", 4, config.R_LIVE)
    assert not forage.score_partial(cand, c)


def test_death_report_becomes_far_goal():
    snap, mem = make(40, 40, [(5, 5), (4, 5), (3, 5)],
                     visible=[(x, y) for x in range(2, 9) for y in range(2, 9)])
    comms.Comms().receive([comms.encode(comms.T_DEATH, 25, 5, 5)], snap, mem)
    assert mem.geo.idx(25, 5) in mem.reports
    safe = safety.get_safe_moves(snap, mem)
    old = config.ENABLE_FAR_GOALS
    config.ENABLE_FAR_GOALS = True
    try:
        act = forage.forage_turn(snap, mem, safe, NoDeadline())
    finally:
        config.ENABLE_FAR_GOALS = old
    assert act == [1]                                   # heads east toward the drop
    assert forage.LAST_TARGET[0] == mem.geo.idx(25, 5)


def test_length_heartbeat_and_longest():
    snap, mem = make(30, 30, [(5 - i, 5) for i in range(12)])
    assert mem.is_longest(snap)
    comms.Comms().receive([comms.encode(comms.T_LENGTH, 0, 0, 20)], snap, mem)
    assert not mem.is_longest(snap)


def test_death_detection_and_broadcast():
    W = 20
    mem = memory.WorldMemory(W, W)
    enemy = [(10, 5), (11, 5), (12, 5), (13, 5), (14, 5)]
    make(W, W, [(5, 5), (4, 5), (3, 5)], others=[(9, enemy, False)], mem=mem, round_num=10)
    snap, mem = make(W, W, [(6, 5), (5, 5), (4, 5)], pearls=[(10, 5), (12, 5), (14, 5)],
                     mem=mem, round_num=11)
    assert mem.deaths_seen and mem.deaths_seen[0][1] == 3
    msg = comms.Comms().choose(snap, mem, None, None, mem.deaths_seen)
    assert comms.decode(msg)[0] == comms.T_DEATH


def test_choose_always_returns_valid_message():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)])
    c = comms.Comms()
    for _ in range(10):
        v = c.choose(snap, mem, mem.geo.idx(9, 9), 8, [])
        assert comms.decode(v) is not None

import config
import memory
from fakes import make

ME = [(1, 1), (1, 2), (1, 3)]


def test_countdown_prediction_and_reset():
    mem = memory.WorldMemory(20, 20)
    make(20, 20, ME, visible=[(5, 5)] + ME, countdowns={(5, 5): 7}, round_num=10, mem=mem)
    t = mem.geo.idx(5, 5)
    assert mem.predicted_countdown(t, 10) == 7
    assert mem.predicted_countdown(t, 16) == 1
    assert mem.predicted_countdown(t, 17) is None     # hit 0 and reset to an unknown value


def test_never_spawns():
    mem = memory.WorldMemory(20, 20)
    make(20, 20, ME, visible=[(5, 5)] + ME, countdowns={(5, 5): -1}, round_num=10, mem=mem)
    assert mem.predicted_countdown(mem.geo.idx(5, 5), 200) == -1


def test_pearl_forgotten_when_seen_empty():
    mem = memory.WorldMemory(20, 20)
    make(20, 20, ME, visible=[(5, 5)] + ME, pearls=[(5, 5)], round_num=10, mem=mem)
    assert mem.geo.idx(5, 5) in mem.pearls
    make(20, 20, ME, visible=[(5, 5)] + ME, round_num=11, mem=mem)
    assert mem.geo.idx(5, 5) not in mem.pearls


def test_stale_pearls_expire():
    mem = memory.WorldMemory(20, 20)
    make(20, 20, ME, visible=[(5, 5)] + ME, pearls=[(5, 5)], round_num=10, mem=mem)
    r = 10 + config.PEARL_STALE_ROUNDS + config.PEARL_CLEANUP_EVERY
    r -= r % config.PEARL_CLEANUP_EVERY
    make(20, 20, ME, visible=ME, round_num=r, mem=mem)
    assert mem.geo.idx(5, 5) not in mem.pearls


def test_out_of_vision_own_segment_is_wall():
    # our chain leaves vision and comes back: the returning part must be a wall
    body = [(5, 5), (6, 5), (7, 5), (8, 5), (8, 6), (7, 6), (6, 6)]
    vis = [(x, y) for x in range(2, 8) for y in range(2, 9)]   # x=8 column hidden
    snap, mem = make(20, 20, body, visible=vis, my_len=7)
    snap.occ = {t: o for t, o in snap.occ.items() if t in snap.visible}
    snap.finalize(mem.geo)
    g = mem.geo
    assert [g.xy(t) for t in snap.body] == [(5, 5), (6, 5), (7, 5)]
    assert g.idx(6, 6) in snap.walls and g.idx(7, 6) in snap.walls

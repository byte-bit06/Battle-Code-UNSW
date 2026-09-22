import safety
from fakes import make


def test_neck_tail_and_kelp_excluded():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (4, 6), (5, 6)], kelp=[(5, 5, 0)])
    safe, risky = safety.classify_moves(snap, mem)
    assert safe == [1]            # N kelp, W neck, S tail -> only E


def test_head_adjacent_to_unmoved_enemy_is_risky():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], my_id=2,
                     others=[(7, [(7, 5), (8, 5), (9, 5)], False)])
    safe, risky = safety.classify_moves(snap, mem)
    assert 1 in risky and 1 not in safe


def test_emergency_always_returns_direction():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (4, 6), (5, 6)],
                     kelp=[(5, 5, 0), (5, 5, 1)])
    d = safety.emergency_move(snap, mem, [])
    assert d in (0, 1, 2, 3)

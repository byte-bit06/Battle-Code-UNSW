"""Rule tests for the local arena simulator.  Run:  python -m pytest -q arena"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "mybot"))
MAPS = os.path.join(os.path.dirname(HERE), "maps")

import sim as S          # noqa: E402
import mapfile           # noqa: E402


def empty_sim(W=10, H=10, dragons=(), kelp=(), portals=(), gaps=None, symmetry=None):
    s = S.Sim.__new__(S.Sim)
    m = mapfile.MapData()
    m.W, m.H, m.symmetry = W, H, symmetry
    m.gaps = gaps or {}
    for x, y, d in kelp:
        (m.north if d in (0, 2) else m.west)[(x, (y + (d == 2)) % H) if d in (0, 2) else ((x + (d == 1)) % W, y)] = (1, -1)
    for x, y, d, pid in portals:
        (m.north if d in (0, 2) else m.west)[(x, (y + (d == 2)) % H) if d in (0, 2) else ((x + (d == 1)) % W, y)] = (2, pid)
    m.dragons = [(did, "A" if did % 2 == 0 else "B", cells) for did, cells in dragons]
    s.map = m
    s.W, s.H = W, H
    s.rng = __import__("random").Random(1)
    s.round, s.over, s.result, s.winner, s.events = 0, False, "", None, []
    s.pearls, s.occ, s.dragons = set(), {}, {}
    s._build_edges()
    s._build_countdowns()
    for did, team, cells in m.dragons:
        dirs = [s._dir_between(cells[i], cells[i - 1]) if i else s._dir_between(cells[1], cells[0])
                for i in range(len(cells))]
        d = S.Dragon(did, team, list(cells), dirs)
        s.dragons[did] = d
        for c in cells:
            s.occ[c] = d
    s.next_id = max(s.dragons) + 1 if s.dragons else 0
    return s


def test_move_and_wrap():
    s = empty_sim(dragons=[(0, [(0, 5), (1, 5), (2, 5)])])
    d = s.dragons[0]
    s.apply(d, ("move", [3]))
    assert d.cells == [(9, 5), (0, 5), (1, 5)]


def test_tail_collision_checked_before_moving():
    s = empty_sim(dragons=[(0, [(5, 5), (4, 5), (4, 6), (5, 6)])])
    d = s.dragons[0]
    s.apply(d, ("move", [2]))                        # into own tail
    assert not d.alive and d.death_cause == "hit itself"


def test_head_to_head_kills_both_and_drops():
    s = empty_sim(dragons=[(0, [(5, 5), (4, 5), (3, 5)]), (1, [(6, 5), (7, 5), (8, 5)])])
    s.apply(s.dragons[0], ("move", [1]))
    assert not s.dragons[0].alive and not s.dragons[1].alive
    assert {(5, 5), (3, 5), (6, 5), (8, 5)} <= s.pearls        # every second segment


def test_kelp_kills():
    s = empty_sim(dragons=[(0, [(5, 5), (4, 5), (3, 5)])], kelp=[(5, 5, 1)])
    s.apply(s.dragons[0], ("move", [1]))
    assert s.dragons[0].death_cause == "hit kelp"


def test_eating_grows():
    s = empty_sim(dragons=[(0, [(5, 5), (4, 5), (3, 5)])])
    s.pearls.add((6, 5))
    d = s.dragons[0]
    s.apply(d, ("move", [1]))
    assert d.length == 4 and (6, 5) not in s.pearls


def test_sprint_costs_segments_and_can_kill():
    s = empty_sim(dragons=[(0, [(5, 5), (4, 5), (3, 5), (2, 5), (1, 5)])])
    d = s.dragons[0]
    s.apply(d, ("move", [1, 1, 0]))                  # 3 steps cost 2 segments
    assert d.alive and d.length == 3 and d.head == (7, 4)
    s.apply(d, ("move", [1, 1, 1]))                  # length 3 can't pay for 3 steps
    assert not d.alive and d.death_cause == "over-sprinted"


def test_split_parent_stays_child_reversed():
    s = empty_sim(dragons=[(0, [(5, 5), (4, 5), (3, 5), (2, 5), (1, 5), (0, 5)])])
    d = s.dragons[0]
    child = s.split(d, 2)
    assert d.cells == [(5, 5), (4, 5), (3, 5), (2, 5)]      # parent did not move
    assert child.cells == [(0, 5), (1, 5)] and child.dirs[0] == 3   # faces away (west)
    assert child.dirs[1] == 3                                  # body points to its head
    assert s.split(child, 1) is False and not child.alive     # illegal split kills


def test_spawn_needs_empty_tile_and_mirror_shares():
    s = empty_sim(W=10, H=10, dragons=[(0, [(2, 2), (1, 2), (0, 2)])],
                  gaps={(2, 2): (3, 3), (7, 2): (3, 3)}, symmetry="y")
    assert len(s.groups) == 1                        # (2,2) and (7,2) share a countdown
    s.cd[(2, 2)] = 1
    s.start_round()
    assert (7, 2) in s.pearls and (2, 2) not in s.pearls      # occupied tile can't spawn
    assert s.countdown((2, 2)) == 3


def test_portal_matches_engine_verified_geometry():
    """Compare every portal move on real maps with mybot/geometry.py, whose
    portal rule was verified in the real engine (8/8 crossings)."""
    import geometry
    for name in ("default", "Colosseum", "queen_of_spades", "trophy", "schooltime"):
        s = S.Sim(os.path.join(MAPS, name + ".map"), seed=0)
        g = geometry.Geo(s.W, s.H)
        for x in range(s.W):
            for y in range(s.H):
                for d in range(4):
                    t, pid = s.edge(x, y, d)
                    if t:
                        g.learn_edge(g.idx(x, y), d, t, pid)
        checked = 0
        for x in range(s.W):
            for y in range(s.H):
                for d in range(4):
                    a = s.step((x, y), d)
                    b = g.step(g.idx(x, y), d)
                    if a == S.KELP_HIT:
                        assert b == -1
                    else:
                        assert b >= 0 and g.xy(b) == a, (name, x, y, d)
                    checked += 1
        assert checked == s.W * s.H * 4


def test_sonar_hits_first_dragon():
    s = empty_sim(dragons=[(0, [(2, 5), (1, 5), (0, 5)]), (1, [(6, 5), (6, 6), (6, 7)])])
    assert s.sonar(s.dragons[0], 123) is s.dragons[1]
    assert s.dragons[1].inbox == [123]


def test_tiebreak_longest():
    s = empty_sim(dragons=[(0, [(1, 1), (0, 1), (9, 1), (8, 1)]), (1, [(1, 5), (0, 5), (9, 5)])])
    s.round = S.MAX_ROUNDS - 1
    s.end_round()
    assert s.over and s.winner == "A"


def test_headless_agent_game_runs():
    import agents
    s = agents.run_headless(os.path.join(MAPS, "default_small.map"), seed=3, max_rounds=120)
    assert s.round == 120 or s.over
    assert any(d.length > 3 for d in s.dragons.values())      # somebody ate


def test_map_dragons_ids_and_teams_match_engine():
    """Engine: ids follow line order, second field is the team (0 A / 1 B)."""
    s = S.Sim(os.path.join(MAPS, "default.map"), seed=0)
    assert sorted(s.dragons) == list(range(8))
    assert [s.dragons[i].team for i in range(8)] == ["A", "B"] * 4
    assert s.dragons[0].head == (0, 0) and s.dragons[0].cells[1] == (1, 0)
    assert len(set(map(id, s.occ.values()))) == 8

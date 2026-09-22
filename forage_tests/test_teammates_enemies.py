"""Enemy tail release, heading risk, careful (tiebreak) mode, portal gamble."""
import config
import forage
import routing
import safety
from fakes import make, NoDeadline


def test_fully_visible_enemy_tail_frees():
    enemy = [(8, 3), (8, 4), (8, 5), (8, 6)]          # tail at (8,6), all neighbours visible
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], others=[(9, enemy, False)])
    g = mem.geo
    assert snap.release[g.idx(8, 6)] == 1 + config.ENEMY_TAIL_MARGIN
    dist, _, _ = routing.bfs(g, snap.head, snap.walls, snap.own_index, 3, 500, 20, release=snap.release)
    assert g.idx(8, 6) in dist and dist[g.idx(8, 6)] > snap.release[g.idx(8, 6)]


def test_enemy_with_hidden_tail_stays_wall():
    enemy = [(7, 5), (8, 5), (9, 5)]
    vis = [(x, y) for x in range(2, 10) for y in range(2, 9)]   # x=10 unseen: tail may continue
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], others=[(9, enemy, False)], visible=vis)
    assert mem.geo.idx(9, 5) not in snap.release


def test_heading_adds_risk():
    snap, mem = make(20, 20, [(2, 2), (1, 2), (0, 2)], others=[(9, [(10, 5), (9, 5), (8, 5)], False)])
    g = mem.geo
    h = snap.heads[0]                                 # facing east
    ahead = forage.head_threat(g, h, g.idx(12, 5), 1)
    side = forage.head_threat(g, h, g.idx(10, 7), 1)
    assert ahead > side


def test_teammates_are_less_risky():
    base = dict(me=[(2, 2), (1, 2), (0, 2)])
    s1, m1 = make(20, 20, others=[(9, [(10, 5), (9, 5), (8, 5)], False)], **base)
    s2, m2 = make(20, 20, others=[(9, [(10, 5), (9, 5), (8, 5)], True)], **base)
    t = m1.geo.idx(11, 5)
    assert forage.head_threat(m2.geo, s2.heads[0], t, 2) < forage.head_threat(m1.geo, s1.heads[0], t, 2)


def test_careful_mode_raises_risk_weights():
    body = [(10 - i, 5) for i in range(12)]
    snap, mem = make(30, 30, body)
    mem.best_len_heard, mem.best_len_round = 8, snap.round     # heard a shorter teammate
    c = forage.make_ctx(snap, mem, [0, 1, 2], NoDeadline())
    assert c.careful and c.c_r == config.C_R * config.CAREFUL_RISK_MULT


def test_portal_gamble_only_when_nothing_else():
    # boxed in by kelp on 3 sides and our neck; the only way out is a portal to an unseen tile
    kelp = [(5, 5, 0), (5, 5, 1)]
    portals = [(5, 5, 2, 4), (15, 15, 2, 4)]
    vis = [(x, y) for x in range(2, 9) for y in range(2, 9)]
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], kelp=kelp, portals=portals, visible=vis)
    safe, risky, gamble = safety.classify_all(snap, mem)
    assert safe == [] and risky == [] and gamble == [2]
    assert safety.get_safe_moves(snap, mem) == [2]


def test_explore_goal_picks_stale_block():
    snap, mem = make(64, 64, [(5, 5), (4, 5), (3, 5)],
                     visible=[(x, y) for x in range(2, 9) for y in range(2, 9)])
    c = forage.make_ctx(snap, mem, [0, 1, 2], NoDeadline())
    goal = forage.explore_goal(c)
    assert goal is not None and mem.explore_goal[0] == goal
    gx, gy = mem.geo.xy(goal)
    assert not (0 <= gx < 8 and 0 <= gy < 8)          # not the block we're standing in

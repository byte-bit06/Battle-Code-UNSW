import routing
from fakes import make


def test_tail_cell_blocked_on_move_1():
    # square loop: head (5,5) -> (4,5) -> (4,6) -> (5,6) tail; S from head hits the tail
    snap, mem = make(12, 12, [(5, 5), (4, 5), (4, 6), (5, 6)])
    g = mem.geo
    assert routing.simulate(g, snap.body, 4, [2], set(), snap.walls) is None
    dist, parent, _ = routing.bfs(g, snap.head, snap.walls, snap.own_index, 4, 500, 20)
    assert dist[g.idx(5, 6)] == 3          # only reachable once the tail has moved


def test_tail_cell_allowed_on_move_2():
    snap, mem = make(12, 12, [(5, 5), (4, 5), (4, 6)])
    g = mem.geo
    dist, _, _ = routing.bfs(g, snap.head, snap.walls, snap.own_index, 3, 500, 20)
    assert dist[g.idx(4, 6)] == 2
    sim = routing.simulate(g, snap.body, 3, [2, 3], set(), snap.walls)   # S then W
    assert sim is not None and g.xy(sim.body[0]) == (4, 6)


def test_eating_delays_tail_release():
    # same route, but eating on move 1 keeps the tail in place for move 2
    snap, mem = make(12, 12, [(5, 5), (4, 5), (4, 6)], pearls=[(5, 6)])
    g = mem.geo
    dist, _, _ = routing.bfs(g, snap.head, snap.walls, snap.own_index, 3, 500, 20)
    assert dist[g.idx(4, 6)] == 2          # BFS alone would allow it...
    assert routing.simulate(g, snap.body, 3, [2, 3], {g.idx(5, 6)}, snap.walls) is None   # ...simulate catches it


def test_other_dragons_are_walls():
    snap, mem = make(12, 12, [(5, 5), (4, 5), (3, 5)], others=[(9, [(6, 4), (6, 5), (6, 6)], False)])
    g = mem.geo
    dist, _, _ = routing.bfs(g, snap.head, snap.walls, snap.own_index, 3, 500, 30)
    assert g.idx(6, 5) not in dist


def test_survives_detects_pocket():
    # 1-wide dead-end corridor made of kelp: a length-6 dragon inside cannot turn around
    kelp = []
    for x in range(2, 9):
        kelp += [(x, 5, 0), (x, 5, 2)]
    kelp.append((8, 5, 1))
    snap, mem = make(20, 20, [(6, 5), (5, 5), (4, 5), (3, 5), (2, 5), (1, 5)], kelp=kelp)
    g = mem.geo
    assert routing.survives(g, snap.body, 6, snap.walls, 6, 200) is False
    snap2, mem2 = make(20, 20, [(6, 5), (5, 5), (4, 5)])
    assert routing.survives(mem2.geo, snap2.body, 3, snap2.walls, 6, 200) is True

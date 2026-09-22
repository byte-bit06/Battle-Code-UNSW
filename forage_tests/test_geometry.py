"""Wrap-around and portal stepping. The portal rule and wrap were verified in
the real engine by probe_bot (8,136 moves + 8 portal crossings, 0 mismatches)."""
import geometry
from geometry import Geo, N, E, S, W, KELP, UNKNOWN, EDGE_KELP, EDGE_PORTAL


def test_wrap_all_borders():
    g = Geo(10, 8)
    assert g.xy(g.step(g.idx(0, 0), N)) == (0, 7)
    assert g.xy(g.step(g.idx(0, 0), W)) == (9, 0)
    assert g.xy(g.step(g.idx(9, 7), E)) == (0, 7)
    assert g.xy(g.step(g.idx(9, 7), S)) == (9, 0)


def test_manhattan_wraps():
    g = Geo(10, 8)
    assert g.manhattan(g.idx(0, 0), g.idx(9, 7)) == 2


def test_kelp_blocks_both_sides():
    g = Geo(10, 10)
    g.learn_edge(g.idx(3, 3), E, EDGE_KELP)
    assert g.step(g.idx(3, 3), E) == KELP
    assert g.step(g.idx(4, 3), W) == KELP
    assert g.step(g.idx(3, 3), S) == g.idx(3, 4)


def test_portal_unknown_partner():
    g = Geo(10, 10)
    g.learn_edge(g.idx(2, 2), E, EDGE_PORTAL, 7)
    assert g.step(g.idx(2, 2), E) == UNKNOWN
    assert g.step(g.idx(3, 2), W) == UNKNOWN


def test_portal_exit_vertical_pair():
    g = Geo(12, 12)
    g.learn_edge(g.idx(2, 2), E, EDGE_PORTAL, 7)   # edge between (2,2) and (3,2)
    g.learn_edge(g.idx(8, 5), E, EDGE_PORTAL, 7)   # edge between (8,5) and (9,5)
    assert g.xy(g.step(g.idx(2, 2), E)) == (9, 5)  # enter from the left, emerge right
    assert g.xy(g.step(g.idx(3, 2), W)) == (8, 5)
    assert g.xy(g.step(g.idx(8, 5), E)) == (3, 2)
    assert g.xy(g.step(g.idx(9, 5), W)) == (2, 2)


def test_portal_exit_horizontal_pair():
    g = Geo(12, 12)
    g.learn_edge(g.idx(4, 1), S, EDGE_PORTAL, 9)
    g.learn_edge(g.idx(6, 7), S, EDGE_PORTAL, 9)
    assert g.xy(g.step(g.idx(4, 1), S)) == (6, 8)
    assert g.xy(g.step(g.idx(4, 2), N)) == (6, 7)
    assert g.xy(g.step(g.idx(6, 7), S)) == (4, 2)
    assert g.xy(g.step(g.idx(6, 8), N)) == (4, 1)


def test_edge_key_canonical():
    g = Geo(5, 5)
    assert g.edge_key(g.idx(1, 1), E) == g.edge_key(g.idx(2, 1), W)
    assert g.edge_key(g.idx(1, 1), S) == g.edge_key(g.idx(1, 2), N)
    assert g.edge_key(g.idx(4, 0), E) == g.edge_key(g.idx(0, 0), W)   # wrap


def test_mirrors():
    g = Geo(10, 6)
    t = g.idx(2, 1)
    assert g.xy(g.mirror(t, "V")) == (7, 1)
    assert g.xy(g.mirror(t, "H")) == (2, 4)
    assert g.xy(g.mirror(t, "R")) == (7, 4)
    assert Geo.mirror_dir(E, "V") == W and Geo.mirror_dir(N, "V") == N
    assert Geo.mirror_dir(N, "H") == S and Geo.mirror_dir(E, "H") == E
    assert Geo.mirror_dir(E, "R") == W and Geo.mirror_dir(N, "R") == S

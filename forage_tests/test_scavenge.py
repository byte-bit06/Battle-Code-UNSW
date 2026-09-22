"""Stage 3: death-drop scavenging."""
import forage
import routing
from fakes import make, NoDeadline


def test_cluster_detected_and_collected():
    drops = [(7, 5), (9, 5), (11, 5), (9, 7)]    # every second segment of a dead dragon
    snap, mem = make(30, 30, [(5, 5), (4, 5), (3, 5)], pearls=drops)
    c = forage.make_ctx(snap, mem, [0, 1, 2], NoDeadline())
    clusters = forage.detect_clusters(c)
    assert len(clusters) == 1 and len(clusters[0]) >= 3
    cand = forage.beam_scavenge(c, clusters[0])
    assert cand is not None and cand.kind == "cluster"
    sim = routing.simulate(mem.geo, snap.body, 3, cand.moves, c.pearls, snap.walls)
    assert sim is not None and len(sim.eaten) >= 3


def test_scavenge_avoids_pocket():
    # the pearls sit in a kelp dead end too short for the grown dragon to turn in
    kelp = [(x, 5, 0) for x in range(6, 10)] + [(x, 5, 2) for x in range(6, 10)] + [(9, 5, 1)]
    body = [(5, 5), (4, 5), (3, 5), (2, 5), (1, 5), (0, 5)]
    snap, mem = make(30, 30, body, pearls=[(7, 5), (8, 5), (9, 5)], kelp=kelp)
    c = forage.make_ctx(snap, mem, [0, 1, 2], NoDeadline())
    for cl in forage.detect_clusters(c):
        cand = forage.beam_scavenge(c, cl)
        if cand is not None:
            assert not forage.is_feasible(cand, c)


def test_no_cluster_below_threshold():
    snap, mem = make(30, 30, [(5, 5), (4, 5), (3, 5)], pearls=[(8, 5), (10, 5)])
    c = forage.make_ctx(snap, mem, [0, 1, 2], NoDeadline())
    assert forage.detect_clusters(c) == []

"""Stage 2 terms."""
import config
import forage
from fakes import make, NoDeadline


def pred(T, d):
    c = forage.Candidate(0, "predicted", d, config.R_PREDICTED, countdown=T)
    return c


def test_timing_exact_is_max():
    best = forage.timing_bonus(pred(3, 3 + config.SPAWN_EAT_OFFSET))
    assert best == config.TIMING_BONUS
    for d in range(1, 12):
        assert forage.timing_bonus(pred(3, d)) <= best


def test_late_is_finite_penalty():
    v = forage.timing_bonus(pred(2, 8))
    assert v < 0 and v != float("-inf")


def test_live_has_no_timing_term():
    assert forage.timing_bonus(forage.Candidate(0, "live", 5, config.R_LIVE)) == 0.0


def _sprint_setup(L, pearls):
    body = [(5 - i, 5) for i in range(L)]
    enemy = [(9, 6), (10, 6), (11, 6)]           # 1 step closer to (8,5)... beats a walk
    snap, mem = make(30, 30, body, my_id=5, pearls=pearls, others=[(9, enemy, False)])
    c = forage.make_ctx(snap, mem, [0, 1, 2], NoDeadline())
    return c


def test_sprint_rejected_without_net_gain():
    c = _sprint_setup(10, [(8, 5)])              # 3-step sprint for 1 pearl: gain 1-2 < 0
    cand = forage.Candidate(c.geo.idx(8, 5), "live", 3, config.R_LIVE)
    assert not forage.score_partial(cand, c)
    assert cand.sprint == 0


def test_sprint_accepted_with_net_gain():
    c = _sprint_setup(10, [(6, 5), (7, 5), (8, 5)])   # 3 steps, eats 3: gain 3-2 = 1
    cand = forage.Candidate(c.geo.idx(8, 5), "live", 3, config.R_LIVE)
    ok = forage.score_partial(cand, c)
    assert ok and cand.sprint == 2 and cand.first == [1, 1, 1]


def test_sprint_respects_reserve():
    c = _sprint_setup(5, [(6, 5), (7, 5), (8, 5)])    # 5-2 = 3 < max(L_RESERVE_MIN, 4)
    cand = forage.Candidate(c.geo.idx(8, 5), "live", 3, config.R_LIVE)
    assert not forage.score_partial(cand, c)


def test_weights_monotonic():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], pearls=[(9, 5)],
                     others=[(9, [(9, 9), (9, 10), (9, 11)], False)])
    for name in ("C_D", "C_R", "C_T", "C_U"):
        scores = []
        old = getattr(config, name)
        try:
            for w in (0.0, old, old * 3):
                setattr(config, name, w)
                c = forage.make_ctx(snap, mem, [0, 1, 2], NoDeadline())
                cand = forage.Candidate(c.geo.idx(9, 5), "live", c.dist[c.geo.idx(9, 5)], config.R_LIVE)
                cand.uncertainty = 0.3
                forage.score_partial(cand, c)
                assert forage.is_feasible(cand, c)
                scores.append(forage.score_full(cand, c))
        finally:
            setattr(config, name, old)
        assert scores[0] >= scores[1] >= scores[2], (name, scores)

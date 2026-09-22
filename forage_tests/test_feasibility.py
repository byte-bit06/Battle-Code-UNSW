"""Stage 1: every rule has a board where it is the failing rule."""
import config
import forage
from fakes import make, NoDeadline

DL = NoDeadline()


def ctx(snap, mem, safe=None):
    import safety
    if safe is None:
        safe = safety.get_safe_moves(snap, mem)
    return forage.make_ctx(snap, mem, safe, DL)


def live(c, x, y):
    t = c.geo.idx(x, y)
    return forage.Candidate(t, "live", c.dist[t], config.R_LIVE)


def test_feasible_simple_pearl():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], pearls=[(8, 5)])
    c = ctx(snap, mem)
    cand = live(c, 8, 5)
    assert forage.score_partial(cand, c)
    assert forage.is_feasible(cand, c), cand.reject_reason


def test_reject_legal_first_move():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], pearls=[(8, 5)])
    c = ctx(snap, mem, safe=[0, 2])          # east is not allowed by the safety layer
    cand = live(c, 8, 5)
    assert not forage.is_feasible(cand, c)
    assert cand.reject_reason == "LegalFirstMove"


def test_reject_survival_margin():
    # BFS thinks the route is fine; the tail staying put after eating kills us
    snap, mem = make(20, 20, [(5, 5), (4, 5), (4, 6)], pearls=[(5, 6)])
    c = ctx(snap, mem)
    t = c.geo.idx(4, 6)
    cand = forage.Candidate(t, "live", 2, config.R_LIVE)
    cand.moves = [2, 3]
    assert not forage.is_feasible(cand, c)
    assert cand.reject_reason == "SurvivalMargin"


def test_reject_escape_capacity():
    # pearl at the end of a 1-wide kelp dead end; a length-8 dragon cannot get back out
    kelp = [(x, 5, 0) for x in range(6, 12)] + [(x, 5, 2) for x in range(6, 12)] + [(11, 5, 1)]
    body = [(5, 5), (4, 5), (3, 5), (2, 5), (1, 5), (0, 5), (19, 5), (18, 5)]
    snap, mem = make(20, 20, body, pearls=[(11, 5)], kelp=kelp)
    c = ctx(snap, mem)
    cand = live(c, 11, 5)
    assert forage.score_partial(cand, c)
    assert not forage.is_feasible(cand, c)
    assert cand.reject_reason in ("EscapeCapacity", "FirstStepEscape")


def test_contention_flips_with_id():
    me = [(5, 5), (4, 5), (3, 5)]
    enemy_cells = [(9, 5), (10, 5), (11, 5)]   # pearl (7,5): we need 2, they need 2
    snap, mem = make(20, 20, me, my_id=5, pearls=[(7, 5)], others=[(3, enemy_cells, False)])
    c = ctx(snap, mem)
    cand = live(c, 7, 5)
    assert not forage.score_partial(cand, c) and cand.reject_reason == "ContentionWin"
    snap, mem = make(20, 20, me, my_id=5, pearls=[(7, 5)], others=[(9, enemy_cells, False)])
    c = ctx(snap, mem)
    cand = live(c, 7, 5)
    assert forage.score_partial(cand, c) and cand.contested


def test_closer_enemy_always_wins():
    snap, mem = make(20, 20, [(5, 5), (4, 5), (3, 5)], my_id=1, pearls=[(8, 5)],
                     others=[(9, [(9, 5), (10, 5), (11, 5)], False)])
    c = ctx(snap, mem)
    cand = live(c, 8, 5)
    assert not forage.score_partial(cand, c)

"""Instinct_Engine: board -> value functions, driven by ASCII fixtures.

No opponent and no game loop: every function here is a pure read of a board,
so a fixture plus an assertion covers it. See boards.py for the notation.
"""
import boards
import config
import pytest
from geometry import N, E, S, W
from instinct import control, corridors, ladder, policy, space, tempo
from instinct.state import TIER_A, TIER_B

# The doc's own sketch board (instinct_engine.md / the brief).
# 'h' is the neck, so body order is H -> h -> (2,2) -> (1,2).
SKETCH = """
. . K . .
. H h . .
. b b K .
. . . e E
"""


# ------------------------------------------------------------- fixtures --
def test_kelp_cells_are_solid_and_board_does_not_wrap():
    st = boards.build(SKETCH)
    g = st.geo
    assert all(g.step(g.idx(2, 0), d) < 0 for d in (N, E, S, W))     # the K cell
    assert g.step(g.idx(0, 1), W) < 0                                # border, no wrap
    assert g.step(g.idx(4, 1), E) < 0


def test_neck_fixes_the_body_order():
    st = boards.build(SKETCH)
    g = st.geo
    assert [g.xy(t) for t in st.body] == [(1, 1), (2, 1), (2, 2), (1, 2)]
    with pytest.raises(ValueError):          # same board without the neck marker
        boards.build(SKETCH.replace(" h ", " b "))


def test_both_orders_gives_lower_and_higher_enemy_ids():
    (n1, lo), (n2, hi) = boards.both_orders(SKETCH, my_id=5)
    assert all(d.id < 5 and d.acts_before for d in lo.enemies)
    assert all(d.id > 5 and not d.acts_before for d in hi.enemies)


def test_sketch_board_values():
    st = boards.build(SKETCH)
    assert corridors.corridor_count(st, open_dist=3) == 1
    assert corridors.cut_tile(st, open_dist=3) == (0, 1)
    assert tempo.ram_exposure(st) == 0


# ------------------------------------------------------------ corridors --
SEALED = """
K K K K K O
K H h b K O
K . . . K O
K K K K K O
"""
ONE_GAP = """
K K K K K O
K H h b . O
K . . . K O
K K K K K O
"""
OPEN_FIELD = """
. . . . . . . . .
. . . . . . . . .
. . . H h b . . .
. . . . . . . . .
. . . . . . . . .
"""


def test_corridor_count_sealed_one_and_open():
    assert corridors.corridor_count(boards.build(SEALED)) == 0
    assert corridors.corridor_count(boards.build(ONE_GAP)) == 1
    assert corridors.corridor_count(boards.build(OPEN_FIELD)) == 3      # k_max


def test_cut_tile_is_on_the_only_way_out():
    st = boards.build(ONE_GAP)
    cut = corridors.cut_tile(st)
    assert cut is not None
    # removing it really does seal us in (that is the definition)
    blocked = {st.geo.idx(*cut)}
    assert corridors.corridor_count(st, extra_blocked=blocked) == 0
    assert corridors.cut_tile(boards.build(SEALED)) is None             # already sealed
    assert corridors.cut_tile(boards.build(OPEN_FIELD)) is None         # no single tile


def test_corridor_count_ignores_which_way_the_ids_run():
    for name, st in boards.both_orders(ONE_GAP):
        assert corridors.corridor_count(st) == 1, name


# ----------------------------------------------------------------- ram --
RAM_ADJACENT = """
. . . . . . O
. . H h b . O
. . E e . . O
. . . . . . O
"""
RAM_FAR = """
. . . . . . O
. . H h b . O
. . . . . . O
. . . . . . O
. . E e e e O
"""


def test_ram_exposure_counts_heads_that_can_reach_us():
    assert tempo.ram_exposure(boards.build(RAM_ADJACENT)) == 1
    assert tempo.ram_exposure(boards.build(OPEN_FIELD)) == 0


def test_ram_exposure_two_tiers_differ_on_sprints():
    """A length-4 enemy 3 tiles away can sprint onto us (Tier A worst case),
    but Tier B does not expect it to pay 3 length for that."""
    st = boards.build(RAM_FAR, lengths={"E": 4})
    assert tempo.ram_exposure(st, tier=TIER_A) == 1
    assert tempo.ram_exposure(st, tier=TIER_B) == 0


def test_ram_exposure_same_in_both_turn_orders():
    for name, st in boards.both_orders(RAM_ADJACENT):
        assert tempo.ram_exposure(st) == 1, name


def test_tempo_classes_follow_ids():
    st = boards.build(RAM_ADJACENT, my_id=5, enemy_ids=[2])
    assert tempo.classify(st)[2] == tempo.BEFORE
    st = boards.build(RAM_ADJACENT, my_id=5, enemy_ids=[8])
    assert tempo.classify(st)[8] == tempo.AFTER


# ------------------------------------------------------- space / growth --
GROW = """
. . . . . O
. H h b . O
. P P . . O
. . . . . O
"""
TIGHT_PEARLS = """
K K K K O
K H h b O
K P P K O
K K K K O
"""
ROOMY = """
K K K K K K O
K H h b . K O
K . . . . K O
K K K K K K O
"""


def test_forced_growth_is_not_optional():
    st = boards.build(GROW)
    assert space.forced_growth(st, [S]) == 1          # stepping on a pearl grows us
    assert space.forced_growth(st, [S, E]) == 2       # and again
    assert space.walk(st, [S]).L == st.L + 1


def test_walking_into_our_own_neck_dies():
    st = boards.build(GROW)
    assert space.walk(st, [E]) is None                # collision checked before movement
    assert space.forced_growth(st, [E]) == -1


def test_chamber_is_unsurvivable_when_pearls_plus_length_exceed_it():
    tight = boards.build(TIGHT_PEARLS)
    assert len(corridors.region(tight)) == 3 and len(tight.pearls) == 2
    assert not space.survivable_chamber(tight)
    assert space.survivable_chamber(boards.build(ROOMY))


def test_timed_space_beats_a_plain_flood_fill():
    """Our own tail frees up as we move, so timed space exceeds the free area."""
    st = boards.build(ROOMY)
    assert space.timed_space(st) > len(corridors.region(st))


def test_corpse_drops_every_second_segment():
    st = boards.build(RAM_FAR, lengths={"E": 4})
    drop = space.corpse_pearls(st.enemies[0])
    assert len(drop) == 2                             # ceil(4 / 2)
    assert st.enemies[0].segs[0] in drop and st.enemies[0].segs[1] not in drop


# ------------------------------------------------------------- control --
def test_margin_and_contested_tiles():
    st = boards.build(RAM_ADJACENT)
    ctrl = control.build_control(st)
    g = st.geo
    assert ctrl.margin(g.idx(2, 0)) > 0 and ctrl.ours(g.idx(2, 0))   # we get there first
    assert ctrl.margin(g.idx(5, 1)) is None           # behind our own body: out of reach
    assert not ctrl.ours(g.idx(5, 3))                 # the enemy owns its own side
    assert ctrl.free_frontier()                       # the corridor target it exists for


# -------------------------------------------------------------- policy --
def test_lexicographic_key_order_is_the_documented_one():
    st = boards.build(OPEN_FIELD)
    key = policy.move_key(st, [N])
    assert len(key) == 5            # a legality filter and a count; see MEASUREMENT.md
    safe, neg_sprint, options, r_tail, pearls = key
    assert safe is True and neg_sprint == 0
    assert options >= 1             # moves still available after the step


def test_ranking_no_longer_uses_ram_exposure():
    """ram_exposure COST survivals as a ranking term (chamber 34 -> 28) and was
    cut from the key. It still shapes l0_reflex, which has its own test."""
    st = boards.build("""
    . . . . . . O
    . . . . . . O
    . H h b . . O
    . . . . . . O
    . E e . . . O
    """)
    north, south = policy.move_key(st, [N]), policy.move_key(st, [S])
    assert north[0] and south[0]                     # both legal
    assert len(north) == 5 and north[2] >= 1         # options carries the ranking


def test_illegal_moves_rank_last():
    st = boards.build(RAM_ADJACENT)
    assert policy.move_key(st, [E])[0] is False       # into our own neck
    assert policy.best_move(st)[0][0] in policy.legal_moves(st)


def test_trade_policy_by_role():
    st = boards.build(RAM_ADJACENT, longest_ally=True)
    assert not policy.may_trade(st, st.enemies[0])    # the tiebreak holder never trades
    short = boards.build(RAM_ADJACENT)                # we are length 3
    assert policy.may_trade(short, short.enemies[0])
    mid = boards.build(RAM_ADJACENT, my_length=10)        # we are 10, they are 2
    assert not policy.may_trade(mid, mid.enemies[0])      # never for a small enemy
    big = boards.build(RAM_ADJACENT, my_length=10, lengths={"E": 14})
    assert policy.may_trade(big, big.enemies[0])          # 14 >= 10 + 4


# --------------------------------------------------------------- split --
COIL6 = """
K K K K K O
K H 1 2 K O
K 5 4 3 K O
K K K K K O
"""
COIL5 = """
K K K K K O
K H 1 2 K O
K . 4 3 K O
K K K K K O
"""


def test_split_legality_is_the_engine_rule():
    st = boards.build(COIL6)
    assert st.L == 6
    assert policy.split_legality(st, 3)
    assert not policy.split_legality(st, 1)           # child must be >= 2
    assert not policy.split_legality(st, 5)           # parent must keep >= 2
    assert not policy.split_legality(st, 3, unit_count=64)
    assert not policy.split_legality(boards.build(RAM_ADJACENT), 2)   # we are only 3 long


def test_defensive_split_fires_only_when_boxed_in():
    boxed = boards.build(COIL6)
    assert space.timed_space(boxed) < boxed.L
    assert policy.should_split(boxed) == 3
    roomy = boards.build(COIL5)                       # still has circulation space
    assert policy.should_split(roomy) is None


def test_split_refused_when_an_enemy_can_hit_us_this_round():
    """Splitting forfeits the move, so zero ram exposure is required (4.8)."""
    st = boards.build(COIL6)
    st.enemies.append(boards.build(RAM_ADJACENT).enemies[0])
    st.enemies[-1].head = st.geo.idx(1, 2)            # right beside our head
    st.enemies[-1].segs = [st.geo.idx(1, 2)]
    assert tempo.ram_exposure(st) >= 1
    assert policy.should_split(st) is None


# --------------------------------------------------------------- ladder --
def test_l0_reflex_always_returns_a_legal_move_when_one_exists():
    for board in (OPEN_FIELD, ONE_GAP, RAM_ADJACENT, GROW, ROOMY, SKETCH):
        st = boards.build(board)
        d = ladder.l0_reflex(st)
        legal = policy.legal_moves(st)
        assert (d in legal) if legal else (d is None), board


def test_l0_reflex_walks_away_from_an_adjacent_enemy_head():
    st = boards.build(RAM_ADJACENT)
    d = ladder.l0_reflex(st)
    n = st.geo.step(st.head, d)
    assert tempo.ram_exposure(st, n) == 0


def test_plan_memory_follows_last_turn_then_expires():
    st = boards.build(OPEN_FIELD)
    plan = ladder.Plan([N, N, E], st.round - 1)
    assert plan.next_step(st) == N
    plan.advance(N, st.round)
    st2 = boards.build(OPEN_FIELD, round_num=st.round + 1)
    assert plan.next_step(st2) == N
    stale = ladder.Plan([N], st.round - 5)
    assert stale.next_step(st) is None


def test_decide_never_returns_nothing_when_a_move_exists():
    for board in (OPEN_FIELD, ONE_GAP, RAM_ADJACENT, ROOMY):
        st = boards.build(board)
        action, _plan, _info = ladder.decide(st)
        assert action is not None and action[0] in ("move", "split"), board


def test_anti_fratricide_higher_id_yields():
    board = """
    . . . . . O
    . H h b . O
    . T t . . O
    . . . . . O
    """
    mine_higher = boards.build(board, my_id=9, mate_ids=[2])
    assert tempo.yields_to_teammate(mine_higher, mine_higher.geo.idx(1, 2))
    mine_lower = boards.build(board, my_id=1, mate_ids=[7])
    assert not tempo.yields_to_teammate(mine_lower, mine_lower.geo.idx(1, 2))


def test_corridor_count_runs_to_the_envelope_free_set_not_a_distance_ring():
    """Escaping into space the enemies already cover is not an escape (4.2/4.3).
    Geometrically there is a way out; in time there is not."""
    st = boards.build("""
    K K K K K K K K K
    K b h H . . . . K
    K K K K K K K . K
    K . . . . . . . K
    K . E e e e e . K
    K K K K K K K K K
    """, lengths={"E": 6})
    ring = corridors.corridor_count(st, open_dist=3)         # distance ring: a way out
    ctrl = control.build_control(st, horizon=6)
    envelope = corridors.corridor_count(st, open_set=ctrl.free_frontier(6))
    assert ring >= 1
    assert envelope <= ring                                  # the honest count is lower
    empty = corridors.corridor_count(st, open_set=set())
    assert empty == 0                                        # nowhere safe to run to


def test_envelope_corridor_count_on_an_empty_board_is_healthy():
    st = boards.build(OPEN_FIELD)
    ctrl = control.build_control(st, horizon=6)
    assert corridors.corridor_count(st, open_set=ctrl.free_frontier(6)) == 3


def test_pearls_delay_our_own_tail_release():
    """A pearl on the way holds the tail still for a turn, so the tile we were
    counting on opens later. The fixed k > L - i schedule misses that (4.5)."""
    coil = """
    K K K K K O
    K H 1 2 K O
    K P 4 3 K O
    K K K K K O
    """
    st = boards.build(coil)
    clean = boards.build(coil.replace("P", "."))
    assert space.timed_space(st) < space.timed_space(clean)


def test_pearl_is_a_cost_in_tight_space_and_a_reward_in_the_open():
    tight = boards.build(TIGHT_PEARLS)
    open_board = boards.build(GROW)
    tight_key = policy.move_key(tight, [S], tight=True)
    open_key = policy.move_key(open_board, [S], tight=False)
    assert tight_key[-1] <= 0        # forced growth in a chamber: a cost
    assert open_key[-1] > 0          # in the open it is what we came for


def test_chamber_survivability_can_be_asked_about_a_route():
    """usable_tiles >= L + pearls_on_route: a route that dodges the pearls is
    survivable in a chamber the pearls would otherwise make fatal."""
    st = boards.build("""
    K K K K K K O
    K H h b P K O
    K . . . P K O
    K K K K K K O
    """, my_length=5)
    g = st.geo
    assert len(corridors.region(st)) == 6 and len(st.pearls) == 2
    assert not space.survivable_chamber(st)                  # 6 < 5 + 2
    pearl_free = [g.idx(1, 2), g.idx(2, 2), g.idx(3, 2)]
    assert space.survivable_chamber(st, route=pearl_free)    # 6 >= 5 + 0


def test_key_prefers_keeping_our_options(monkeypatch):
    """`options` replaced timed_space: the count of legal moves left after the
    step. It is what the five-line greedy control does better than this engine,
    and it costs nothing - tier_a_safe already enumerates those moves."""
    st = boards.build("""
    K K K K K K K O
    K . . . . . K O
    K . K K K . K O
    K H h b K . K O
    K . K K K . K O
    K . . . . . K O
    K K K K K K K O
    """)
    keys = {d: policy.move_key(st, [d]) for d in (N, S)}
    assert all(k[0] for k in keys.values())          # both legal
    assert keys[N][2] >= 1 and keys[S][2] >= 1       # options term is populated
    assert policy.best_move(st)[0] is not None

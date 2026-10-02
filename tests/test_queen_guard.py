"""Algorithm A verification tests (plan Part 5)."""
from board import Board
from helper import Direction
from queen_guard import (count_exits, find_target_direction, is_adjacent_to_enemy_head,
                         queen_turn, rank_directions, worker_turn)
from core import get_safe_directions
from helper import Position

N, E, S, W = Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST


def actions(capsys) -> list[str]:
    """The MOVE / SPLIT lines the turn printed."""
    return [l for l in capsys.readouterr().out.splitlines() if l.startswith(("MOVE", "SPLIT"))]


def target(board):
    ct, game = board.load()
    return find_target_direction(ct, game, get_safe_directions(ct, game))


# ---------------------------------------------------------------- A-Stage 2: foraging

def test_pearl_north_and_safe_moves_north():
    assert target(Board(20, 20, (5, 5), facing="E").pearl(5, 3)) == N


def test_pearl_north_blocked_moves_sideways():
    b = Board(20, 20, (5, 5)).pearl(5, 3).segment(5, 4, dragon_id=1, team="B")
    assert target(b) in (E, W)


def test_pearl_in_corner_reduces_primary_axis_first():
    # dx = +3, dy = -2 -> east is the dominant axis
    assert target(Board(20, 20, (5, 5)).pearl(8, 3)) == E


def test_primary_blocked_uses_secondary_axis():
    b = Board(20, 20, (5, 5)).pearl(8, 3).kelp(5, 5, E)
    assert target(b) == N


def test_primary_and_secondary_blocked_takes_any_safe():
    b = Board(20, 20, (5, 5), facing="S").pearl(8, 3).kelp(5, 5, E).kelp(5, 5, N)
    assert target(b) in (S, W)


def test_no_pearl_prefers_most_exits():
    # three safe moves; west leads into a pocket with one exit, south into two
    b = Board(20, 20, (5, 5), facing="N")
    b.segment(5, 6)                                 # neck behind us blocks S
    b.kelp(4, 5, N).kelp(4, 5, W)                   # west pocket: only S exit from (4,5)
    b.kelp(5, 4, N)                                 # north tile: E and W exits only
    ct, game = b.load()
    ranked = rank_directions(ct, game, get_safe_directions(ct, game))
    exits = {d: e for d, e, _ in ranked}
    assert exits[E] == 3 and exits[N] == 2 and exits[W] == 1
    assert ranked[0][0] == E


def test_no_pearl_open_field_keeps_heading():
    assert target(Board(20, 20, (5, 5), facing="W")) == W


def test_dead_end_avoided_even_toward_pearl():
    # the pearl is north, but (5,4) is a dead end: kelp N, E, W around it
    b = Board(20, 20, (5, 5)).pearl(5, 2)
    b.kelp(5, 4, N).kelp(5, 4, E).kelp(5, 4, W)
    ct, game = b.load()
    assert count_exits(ct, Position(5, 5), Position(5, 4)) == 0
    assert target(b) != N


def test_two_deep_pocket_is_a_trap_even_with_pearl_inside():
    """queen_of_spades: east of (18,9) is (19,9) -> only exit north -> (19,8),
    a dead end. One exit at step one fooled the 1-step lookahead; the queen
    and later a worker both died there."""
    b = Board(25, 35, (18, 9), facing="S", length=4).pearl(19, 8)
    b.segment(18, 8, facing="S")                            # neck
    b.kelp(19, 9, S).kelp(19, 9, E)                         # (19,9): only N leads on
    b.kelp(19, 8, N).kelp(19, 8, E).kelp(19, 8, W)          # (19,8): dead end
    ct, game = b.load()
    ranked = rank_directions(ct, game, get_safe_directions(ct, game))
    trapped = {d: t for d, _, t in ranked}
    assert trapped[E] is True and trapped[S] is False and trapped[W] is False
    assert ranked[0][0] != E


def test_all_moves_trapped_picks_biggest_space():
    # boxed in a 1-wide corridor: north is 1 tile deep, south is 3 tiles deep
    b = Board(20, 20, (5, 5), facing="E", length=10)
    b.segment(4, 5, facing="E")                              # neck west
    b.kelp(5, 5, E)
    for y in range(1, 9):
        b.kelp(5, y, E).kelp(5, y, W)
    b.kelp(5, 4, N).kelp(5, 8, S)
    ct, game = b.load()
    ranked = rank_directions(ct, game, get_safe_directions(ct, game))
    assert all(t for _, _, t in ranked)
    assert ranked[0][0] == S


def _curled_dragon(pearl_in_pocket=False):
    """Length 5, head (5,5) facing E. Body runs (5,6) <- (6,6) <- (7,6) <- tail (7,5).
    The only safe move is E into (6,5), boxed by kelp above and our tail to its east."""
    b = Board(20, 20, (5, 5), facing="E", length=5)
    b.segment(5, 6, facing="N").segment(6, 6, facing="W")
    b.segment(7, 6, facing="W").segment(7, 5, facing="S")
    b.kelp(6, 5, N).kelp(5, 5, N).kelp(5, 5, W)
    if pearl_in_pocket:
        b.pearl(6, 5)
    return b


def test_own_body_order_follows_segments_from_head():
    ct, game = _curled_dragon().load()
    from queen_guard import own_body_order
    order = own_body_order(ct)
    assert order == {Position(5, 5): 0, Position(5, 6): 1, Position(6, 6): 2,
                     Position(7, 6): 3, Position(7, 5): 4}


def test_own_body_order_numbers_tail_end_when_middle_is_out_of_vision():
    """Length 8, head (5,5). Body runs east to (9,5)/(9,6), outside the 7x7
    window (x 2..8), and comes back to the tail at (7,6)."""
    from queen_guard import own_body_order
    b = Board(20, 20, (5, 5), facing="W", length=8)
    b.segment(6, 5, facing="W").segment(7, 5, facing="W").segment(8, 5, facing="W")
    b.segment(9, 5, facing="W").segment(9, 6, facing="N")      # hidden by vision
    b.segment(8, 6, facing="E").segment(7, 6, facing="E")      # tail end, visible again
    ct, game = b.load()
    assert own_body_order(ct) == {Position(5, 5): 0, Position(6, 5): 1, Position(7, 5): 2,
                                  Position(8, 5): 3, Position(8, 6): 6, Position(7, 6): 7}


def test_pocket_walled_by_own_tail_is_not_a_trap():
    """The tail leaves (7,5) before we get there, so the pocket opens east."""
    from queen_guard import own_body_order, reachable_area
    ct, game = _curled_dragon().load()
    here, dest = Position(5, 5), Position(6, 5)
    assert reachable_area(ct, here, dest, 5) == 1                        # body as walls
    assert reachable_area(ct, here, dest, 5, own_body_order(ct)) == 5    # timed body
    ranked = rank_directions(ct, game, get_safe_directions(ct, game))
    assert ranked == [(E, 0, False)]


def test_eating_pearl_stalls_tail_so_pocket_stays_shut():
    from queen_guard import own_body_order, reachable_area
    ct, game = _curled_dragon(pearl_in_pocket=True).load()
    assert reachable_area(ct, Position(5, 5), Position(6, 5), 5, own_body_order(ct)) == 1


def test_returns_none_only_when_no_safe_dirs():
    b = Board(20, 20, (5, 5)).segment(5, 4).segment(5, 6).segment(4, 5).segment(6, 5)
    assert target(b) is None


# ---------------------------------------------------------------- A-Stage 3: threat avoidance

def test_adjacency_helper():
    assert is_adjacent_to_enemy_head(Position(6, 5), [Position(7, 5)], 20, 20)
    assert not is_adjacent_to_enemy_head(Position(6, 5), [Position(8, 5)], 20, 20)
    assert is_adjacent_to_enemy_head(Position(0, 5), [Position(19, 5)], 20, 20)  # wraps


def test_queen_avoids_tile_next_to_enemy_head(capsys):
    # pearl east; enemy head one tile east of the pearl tile
    b = Board(20, 20, (5, 5), facing="E").pearl(6, 5)
    b.segment(7, 5, dragon_id=1, team="B", head=True, facing="W")
    ct, game = b.load()
    kind, move = queen_turn(ct, game, {"has_split": True})
    assert kind == "move" and move != E


def test_queen_not_immobilised_when_every_tile_is_threatened(capsys):
    b = Board(20, 20, (5, 5), facing="N").pearl(5, 4)
    for x, y in [(5, 3), (7, 5), (5, 7), (3, 5)]:   # each neighbour touches an enemy head
        b.segment(x, y, dragon_id=1, team="B", head=True)
    ct, game = b.load()
    assert queen_turn(ct, game, {"has_split": True}) == ("move", N)


def test_no_enemy_no_change(capsys):
    ct, game = Board(20, 20, (5, 5), facing="E").pearl(8, 5).load()
    assert queen_turn(ct, game, {"has_split": True}) == ("move", E)


def test_worker_ignores_threats(capsys):
    b = Board(20, 20, (5, 5), my_id=2, facing="E").pearl(6, 5)
    b.segment(7, 5, dragon_id=1, team="B", head=True, facing="W")
    ct, game = b.load()
    assert worker_turn(ct, game) == ("move", E)


# ---------------------------------------------------------------- A-Stage 4: the one split

def test_no_split_at_length_7(capsys):
    ct, game = Board(20, 20, (5, 5), length=7).load()
    state = {"has_split": False}
    assert queen_turn(ct, game, state)[0] == "move"
    assert state["has_split"] is False


def test_split_at_length_8(capsys):
    ct, game = Board(20, 20, (5, 5), length=8).load()
    state = {"has_split": False}
    assert queen_turn(ct, game, state) == ("split", 4)
    assert state["has_split"] is True
    assert actions(capsys) == ["SPLIT 4"]


def test_no_split_with_enemy_visible(capsys):
    b = Board(20, 20, (5, 5), length=20).segment(8, 8, dragon_id=1, team="B", head=True)
    ct, game = b.load()
    assert queen_turn(ct, game, {"has_split": False})[0] == "move"


def test_never_splits_twice(capsys):
    ct, game = Board(20, 20, (5, 5), length=20).load()
    assert queen_turn(ct, game, {"has_split": True})[0] == "move"


def test_workers_never_split(capsys):
    ct, game = Board(20, 20, (5, 5), my_id=2, length=20).load()
    assert worker_turn(ct, game)[0] == "move"


# ---------------------------------------------------------------- integration

def test_every_turn_sends_exactly_one_action(capsys):
    boards = [Board(20, 20, (5, 5), length=8),
              Board(20, 20, (5, 5)).pearl(6, 6),
              Board(11, 11, (5, 5)).segment(5, 4).segment(5, 6).segment(4, 5).segment(6, 5)]
    for b in boards:
        ct, game = b.load()
        queen_turn(ct, game, {"has_split": False})
        assert len(actions(capsys)) == 1
        ct, game = b.load()
        worker_turn(ct, game)
        assert len(actions(capsys)) == 1

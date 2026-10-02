"""Stage 0 verification tests (plan Part 4)."""
import time

import pytest

from board import Board
from helper import Direction, Position, Team
import core
from core import (direction_toward, find_nearest_pearl, get_fallback_move, get_role,
                  get_safe_directions, resolve_destination)

N, E, S, W = Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST
ALL = [N, E, S, W]


# ---------------------------------------------------------------- 0.1 role detection

@pytest.mark.parametrize("team", ["A", Team.A])
def test_role_team_a(team):
    assert get_role(0, team) == "queen"
    assert get_role(1, team) == "worker"  # enemy queen's ID is never ours
    assert get_role(2, team) == "hunter"
    assert get_role(3, team) == "worker"
    assert get_role(9, team) == "worker"


@pytest.mark.parametrize("team", ["B", Team.B])
def test_role_team_b(team):
    assert get_role(1, team) == "queen"
    assert get_role(0, team) == "worker"
    assert get_role(3, team) == "hunter"
    assert get_role(2, team) == "worker"
    assert get_role(8, team) == "worker"


def test_enemy_queen_id():
    assert core.get_enemy_queen_id(Team.A) == 1
    assert core.get_enemy_queen_id(Team.B) == 0


# ---------------------------------------------------------------- 0.2 safe move validator

def test_open_board_all_safe():
    ct, game = Board(11, 11, (5, 5)).load()
    assert get_safe_directions(ct, game) == ALL


def test_kelp_wall_blocks():
    ct, game = Board(11, 11, (5, 5)).kelp(5, 5, E).load()
    assert get_safe_directions(ct, game) == [N, S, W]


def test_kelp_seen_from_neighbour_side_blocks():
    # kelp stored as the WEST edge of (6,5) is the same edge as the EAST edge of (5,5)
    ct, game = Board(11, 11, (5, 5)).kelp(6, 5, W).load()
    assert E not in get_safe_directions(ct, game)


def test_own_body_blocks():
    ct, game = Board(11, 11, (5, 5)).segment(5, 4).load()
    assert N not in get_safe_directions(ct, game)


def test_own_tail_blocks():
    # length-3 dragon curled so its tail sits directly north of the head
    b = Board(11, 11, (5, 5), facing="W")
    b.segment(6, 5, facing="W").segment(6, 4, facing="S")  # neck, then tail
    b.segment(5, 4, facing="E")  # tail tile north of head (length 4)
    ct, game = b.load()
    safe = get_safe_directions(ct, game)
    assert N not in safe and E not in safe
    assert safe == [S, W]


def test_enemy_head_and_body_block():
    b = Board(11, 11, (5, 5))
    b.segment(6, 5, dragon_id=1, team="B", head=True)
    b.segment(5, 6, dragon_id=1, team="B")
    ct, game = b.load()
    assert get_safe_directions(ct, game) == [N, W]


def test_fully_surrounded_returns_empty():
    b = Board(11, 11, (5, 5))
    b.segment(5, 4).segment(5, 6).segment(4, 5)
    b.kelp(5, 5, E)
    ct, game = b.load()
    assert get_safe_directions(ct, game) == []


# ---------------------------------------------------------------- 0.3 destination resolver: wrap

def test_wrap_east_boundary():
    ct, game = Board(11, 11, (10, 5)).load()
    assert resolve_destination(ct, Position(10, 5), E) == Position(0, 5)


@pytest.mark.parametrize("head,direction,expected", [
    ((0, 0), N, (0, 9)), ((0, 0), W, (11, 0)),
    ((11, 9), S, (11, 0)), ((11, 9), E, (0, 9)),
    ((0, 9), S, (0, 0)), ((11, 0), N, (11, 9)),
])
def test_wrap_every_corner(head, direction, expected):
    ct, game = Board(12, 10, head).load()  # non-square to catch width/height mix-ups
    assert resolve_destination(ct, Position(*head), direction) == Position(*expected)


def test_wrap_blocked_by_segment_across_border():
    ct, game = Board(11, 11, (10, 0)).segment(0, 0, dragon_id=1, team="B").load()
    assert E not in get_safe_directions(ct, game)


def test_kelp_on_map_border_blocks():
    ct, game = Board(11, 11, (0, 0)).kelp(0, 0, N).load()
    assert N not in get_safe_directions(ct, game)


def test_resolve_kelp_is_none():
    ct, game = Board(11, 11, (5, 5)).kelp(5, 5, S).load()
    assert resolve_destination(ct, Position(5, 5), S) is None


def test_resolve_outside_vision_is_none():
    ct, game = Board(20, 20, (5, 5)).load()
    assert resolve_destination(ct, Position(15, 15), N) is None


def test_every_position_and_direction_never_raises():
    for width, height in [(10, 10), (11, 11), (12, 17)]:
        for x in range(width):
            for y in range(height):
                ct, game = Board(width, height, (x, y)).load()
                safe = get_safe_directions(ct, game)
                assert safe == ALL
                for d in ALL:
                    dest = resolve_destination(ct, Position(x, y), d)
                    dx, dy = d.get_offset()
                    assert dest == Position((x + dx) % width, (y + dy) % height)


# ---------------------------------------------------------------- 0.3 destination resolver: portals

def test_portal_horizontal_exit_in_vision():
    # north edge of the head tile is portal 7; partner is north edge of (3,4)
    b = Board(12, 12, (5, 5)).portal(7, 5, 5, N).portal(7, 3, 4, N)
    ct, game = b.load()
    assert resolve_destination(ct, Position(5, 5), N) == Position(3, 3)
    assert N in get_safe_directions(ct, game)


def test_portal_is_not_the_adjacent_tile():
    b = Board(12, 12, (5, 5)).portal(7, 5, 5, N).portal(7, 3, 4, N)
    ct, game = b.load()
    assert resolve_destination(ct, Position(5, 5), N) != Position(5, 4)


def test_portal_partner_on_south_side():
    # south edge of head is portal 9; partner is north edge of (7,3) -> exit going south is (7,3)
    b = Board(12, 12, (5, 5)).portal(9, 5, 5, S).portal(9, 7, 3, N)
    ct, game = b.load()
    assert resolve_destination(ct, Position(5, 5), S) == Position(7, 3)


def test_portal_vertical():
    # west edge of head is portal 4; partner is west edge of (8,7) -> exit going west is (7,7)
    b = Board(12, 12, (5, 5)).portal(4, 5, 5, W).portal(4, 8, 7, W)
    ct, game = b.load()
    assert resolve_destination(ct, Position(5, 5), W) == Position(7, 7)


def test_portal_partner_out_of_vision_is_unknown():
    b = Board(20, 20, (5, 5)).portal(11, 5, 5, E).portal(11, 15, 15, E)
    ct, game = b.load()
    assert resolve_destination(ct, Position(5, 5), E) is None
    assert E not in get_safe_directions(ct, game)


def test_portal_exit_just_outside_vision_is_not_safe():
    # partner edge is on the top border of vision; the exit tile beyond it is not visible
    b = Board(20, 20, (5, 5)).portal(7, 5, 5, N).portal(7, 3, 2, N)
    ct, game = b.load()
    assert resolve_destination(ct, Position(5, 5), N) == Position(3, 1)
    assert N not in get_safe_directions(ct, game)


def test_portal_exit_occupied_is_not_safe():
    b = Board(12, 12, (5, 5)).portal(7, 5, 5, N).portal(7, 3, 4, N)
    b.segment(3, 3, dragon_id=1, team="B")
    ct, game = b.load()
    assert N not in get_safe_directions(ct, game)


def test_portal_ignores_other_portal_ids():
    b = Board(12, 12, (5, 5)).portal(7, 5, 5, N).portal(8, 3, 4, N)
    ct, game = b.load()
    assert resolve_destination(ct, Position(5, 5), N) is None


# ---------------------------------------------------------------- 0.4 nearest pearl finder

def test_no_pearls():
    ct, game = Board(11, 11, (5, 5)).load()
    assert find_nearest_pearl(ct, game) is None


def test_nearest_pearl_picked():
    b = Board(20, 20, (5, 5)).pearl(8, 8).pearl(5, 3).pearl(2, 6)
    ct, game = b.load()
    assert find_nearest_pearl(ct, game) == Position(5, 3)


def test_nearest_pearl_across_wrap():
    # head at (1,1): pearl at (19,1) is 2 away through the border, (4,1) is 3 away
    b = Board(20, 20, (1, 1)).pearl(4, 1).pearl(19, 1)
    ct, game = b.load()
    assert find_nearest_pearl(ct, game) == Position(19, 1)


# ---------------------------------------------------------------- 0.5 direction toward target

@pytest.mark.parametrize("here,target,expected", [
    ((5, 5), (5, 2), N), ((5, 5), (5, 8), S), ((5, 5), (8, 5), E), ((5, 5), (2, 5), W),
    ((5, 5), (8, 6), E),   # dominant axis is x
    ((5, 5), (6, 9), S),   # dominant axis is y
    ((5, 5), (7, 7), E),   # tie -> horizontal
])
def test_direction_toward_basic(here, target, expected):
    assert direction_toward(Position(*here), Position(*target), 20, 20) == expected


def test_direction_toward_wraps():
    # target to the west is 2 steps by going east across the border
    assert direction_toward(Position(19, 5), Position(1, 5), 20, 20) == E
    assert direction_toward(Position(1, 5), Position(19, 5), 20, 20) == W
    assert direction_toward(Position(5, 0), Position(5, 18), 20, 20) == N


def test_direction_toward_same_tile():
    assert direction_toward(Position(3, 3), Position(3, 3), 20, 20, [S, W]) == S
    assert direction_toward(Position(3, 3), Position(3, 3), 20, 20) in ALL


# ---------------------------------------------------------------- 0.6 fallback move

def test_fallback_returns_safe_direction():
    ct, game = Board(11, 11, (5, 5)).segment(5, 4).load()
    assert get_fallback_move(ct, game) == E


def test_fallback_keeps_heading_when_safe():
    ct, game = Board(11, 11, (5, 5), facing="S").load()
    assert get_fallback_move(ct, game) == S


def test_fallback_does_not_orbit_kelp_pocket():
    """queen_of_spades replay: leaving the kelp pocket at (19,14) facing east,
    an N-first fallback turned straight back in and looped a 2x2 square."""
    b = Board(25, 35, (19, 15), my_id=1, team="B", facing="E")
    b.segment(18, 15, facing="E").segment(18, 14, facing="S")  # neck, tail
    b.kelp(19, 14, N).kelp(19, 14, E)
    ct, game = b.load()
    assert get_safe_directions(ct, game) == [N, E, S]
    assert get_fallback_move(ct, game) == E


def test_fallback_head_on_when_surrounded():
    b = Board(11, 11, (5, 5))
    b.segment(5, 4).segment(4, 5).kelp(5, 5, E)
    b.segment(5, 6, dragon_id=1, team="B", head=True)
    ct, game = b.load()
    assert get_safe_directions(ct, game) == []
    assert get_fallback_move(ct, game) == S


def test_fallback_never_head_on_with_ally():
    b = Board(11, 11, (5, 5))
    b.segment(5, 4).segment(4, 5).kelp(5, 5, E)
    b.segment(5, 6, dragon_id=2, team="A", head=True)
    ct, game = b.load()
    assert get_fallback_move(ct, game) == N


def test_fallback_north_when_nothing_else():
    b = Board(11, 11, (5, 5))
    b.kelp(5, 5, N).kelp(5, 5, E).kelp(5, 5, S).kelp(5, 5, W)
    ct, game = b.load()
    move = get_fallback_move(ct, game)
    assert move is not None and move == N


def test_fallback_gambles_on_unknown_portal_before_certain_death():
    b = Board(20, 20, (5, 5))
    b.segment(5, 4).segment(4, 5).segment(5, 6)
    b.portal(11, 5, 5, E)  # partner not in vision
    ct, game = b.load()
    assert get_fallback_move(ct, game) == E


# ---------------------------------------------------------------- performance

def test_stage0_is_cheap():
    """Wall-clock sanity check. The judge's CPU-point budget is measured with
    `unswbc run --sandbox` instead (see README)."""
    b = Board(32, 32, (5, 5)).pearl(6, 7).portal(3, 5, 5, N).portal(3, 7, 4, N)
    ct, game = b.load()
    start = time.perf_counter()
    for _ in range(200):
        safe = get_safe_directions(ct, game)
        find_nearest_pearl(ct, game)
        direction_toward(ct.get_position(), Position(6, 7), 32, 32, safe)
        get_fallback_move(ct, game, safe)
    per_turn_ms = (time.perf_counter() - start) / 200 * 1000
    assert per_turn_ms < 2.0

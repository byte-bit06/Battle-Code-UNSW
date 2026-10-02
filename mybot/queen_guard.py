"""Algorithm A: Queen Guard (plan Part 5).

The queen chases pearls, steps away from enemy heads, and splits exactly once
to make the hunter. Workers chase pearls with no threat filter and never split.
Every function reads the current turn only; the single exception is the
queen's `has_split` flag, which the caller owns and passes in.
"""
import helper
from helper import Direction, Position
from core import (direction_toward, find_nearest_pearl, get_fallback_move,
                  get_safe_directions, resolve_destination, toroidal_delta,
                  toroidal_distance)
from grid import DIR_INDEX, grid_for

SPLIT_MIN_LENGTH = 8   # A-Stage 4: both halves keep >= 4 segments
SPLIT_SIZE = 4         # segments handed to the child (the hunter)
TRAP_AREA_CAP = 20     # most free space we demand; vision shows ~48 tiles


# ---------------------------------------------------------------- vision helpers
# The lookahead work runs on grid.Grid (plain integers, built once a turn).
# These wrappers keep a Position-based API for tests and callers.

def visible_enemy_heads(ct) -> list[Position]:
    """Positions of every enemy head in the 7x7 window."""
    my_team = ct.get_team()
    heads = []
    for tile in ct.get_tiles():
        part = tile.get_dragon()
        if part is not None and part.is_head() and part.get_team() != my_team:
            heads.append(tile.get_position())
    return heads


def count_exits(ct, here: Position, dest: Position) -> int:
    """1-step lookahead: how many safe moves we would have after stepping
    from `here` onto `dest`. `here` becomes our neck, so it never counts;
    the tail is treated as staying put (conservative, as in Stage 0)."""
    g = grid_for(ct, helper.game)
    return g.exits(g.index(here), g.index(dest))


def own_body_order(ct) -> dict[Position, int]:
    """Our visible segments numbered from the head (0) to the tail (L-1).

    Each body segment faces the next segment toward the head (checked
    against the engine). Two walks:
      - from the head backwards: whichever segment points at the current
        one comes next, until the body leaves vision;
      - from the tail forwards, if the tail is visible: it is L-1, the
        segment it points at is L-2, and so on. A segment is only taken to
        be the tail when none of its neighbours is hidden and none of ours
        points at it (otherwise its predecessor may just be out of view).
    Middle segments seen by neither walk get no number."""
    g = grid_for(ct, helper.game)
    return {g.position(i): k for i, k in enumerate(g.body_order()) if k >= 0}


def reachable_area(ct, here: Position, dest: Position, limit: int,
                   body_order: dict[Position, int] | None = None) -> int:
    """Tiles reachable from `dest` (reached on move 1) inside vision, counting
    up to `limit`. Kelp, enemy dragons and unknown portal exits block.

    Our own body is timed: the segment numbered i from the head (length L)
    has left its tile by move t when t > L - i (the tail, i = L-1, is still
    there on move 1 and gone on move 2). Eating the pearl on `dest` stalls
    the tail a move, so that adds one move of delay. Pearls further along
    are unknowable; the next turn's exact safety check still covers them.
    `here` becomes our neck and is timed as segment 0. Segments with no
    number (body out of vision) stay blocked. With body_order None the
    whole body is treated as wall."""
    g = grid_for(ct, helper.game)
    order = None
    if body_order is not None:
        order = [-1] * len(g.tiles)
        for pos, k in body_order.items():
            i = g.index(pos)
            if i >= 0:
                order[i] = k
    return g.area(g.index(dest), limit, order)


def is_adjacent_to_enemy_head(dest: Position, enemy_heads: list[Position],
                              width: int, height: int) -> bool:
    """True if any enemy head is one step (or zero) from `dest`, so that
    enemy could move onto `dest` this round and kill us head-on."""
    return any(toroidal_distance(dest, head, width, height) <= 1 for head in enemy_heads)


# ---------------------------------------------------------------- A-Stage 2: foraging

def approach_directions(here: Position, target: Position, width: int, height: int):
    """(primary, secondary) directions toward target. Primary is the dominant
    axis; secondary is the other axis, or None if that axis is already aligned."""
    dx = toroidal_delta(here.x, target.x, width)
    dy = toroidal_delta(here.y, target.y, height)
    if dx == 0 and dy == 0:
        return None, None
    primary = direction_toward(here, target, width, height)
    if primary in (Direction.EAST, Direction.WEST):
        secondary = Direction.SOUTH if dy > 0 else Direction.NORTH if dy < 0 else None
    else:
        secondary = Direction.EAST if dx > 0 else Direction.WEST if dx < 0 else None
    return primary, secondary


def trap_threshold(length: int) -> int:
    """A move is a trap if it leads into fewer free tiles than this.
    Capped because vision only ever shows ~48 tiles."""
    return min(length, TRAP_AREA_CAP)


def rank_directions(ct, game, safe_dirs: list[Direction]) -> list[tuple[Direction, int, bool]]:
    """Safe directions best-first, as (direction, exits, trapped).

    Sort key, in order:
      1. traps last: the space past this move (flood fill in vision) is
         smaller than our length. Among traps, the biggest space first.
      2. toward the nearest pearl: primary axis, then secondary, then the rest
      3. more exits first (1-step lookahead: open space over corridors)
      4. keep the current heading (stops the 2x2 orbit seen in Stage 0)
    Remaining ties keep the helper's N, E, S, W order.
    """
    here = ct.get_position()
    width, height = game.get_map_size()
    pearl = find_nearest_pearl(ct, game)
    primary, secondary = (approach_directions(here, pearl, width, height)
                          if pearl is not None else (None, None))
    facing = ct.get_dir()
    need = trap_threshold(ct.get_length())
    g = grid_for(ct, game)
    order = g.body_order() if safe_dirs else None

    scored = []
    for direction in safe_dirs:
        dest = g.nbr[g.head][DIR_INDEX[direction]]
        exits = g.exits(g.head, dest)
        area = g.area(dest, need, order)
        trapped = area < need
        tier = 0 if direction == primary else 1 if direction == secondary else 2
        key = (trapped, -area if trapped else 0, tier, -exits, direction != facing)
        scored.append((key, direction, exits, trapped))
    scored.sort(key=lambda item: item[0])
    return [(direction, exits, trapped) for _, direction, exits, trapped in scored]


def find_target_direction(ct, game, safe_dirs: list[Direction]) -> Direction | None:
    """Best foraging direction, or None only when safe_dirs is empty."""
    ranked = rank_directions(ct, game, safe_dirs)
    return ranked[0][0] if ranked else None


# ---------------------------------------------------------------- A-Stage 4: the one split

def should_split(ct, has_split: bool, enemy_heads: list[Position]) -> bool:
    return (not has_split
            and ct.get_length() >= SPLIT_MIN_LENGTH
            and not enemy_heads
            and ct.can_split(SPLIT_SIZE))


# ---------------------------------------------------------------- turns

def queen_turn(ct, game, state: dict) -> tuple[str, object]:
    """One queen turn. `state["has_split"]` is the only memory between turns.
    Sends exactly one action and returns it as ("split", n) or ("move", dir)."""
    enemy_heads = visible_enemy_heads(ct)

    # A-Stage 4: split once to create the hunter
    if should_split(ct, state.get("has_split", False), enemy_heads):
        ct.do_split(SPLIT_SIZE)
        state["has_split"] = True
        return "split", SPLIT_SIZE

    # A-Stage 2: forage
    safe_dirs = get_safe_directions(ct, game)
    ranked = rank_directions(ct, game, safe_dirs)
    choice = ranked[0][0] if ranked else None

    # A-Stage 3: step away from enemy heads if a decent alternative exists.
    # The alternative is the next-best forage choice that is not adjacent to
    # an enemy head and not a trap. If none exists we keep the forage
    # choice: adjacency is a preference, never a reason to freeze.
    if choice is not None and enemy_heads:
        width, height = game.get_map_size()
        here = ct.get_position()
        for direction, exits, trapped in ranked:
            dest = resolve_destination(ct, here, direction)
            if not trapped and not is_adjacent_to_enemy_head(dest, enemy_heads, width, height):
                choice = direction
                break

    if choice is None:
        choice = get_fallback_move(ct, game, safe_dirs)
    ct.make_move(choice)
    return "move", choice


def worker_turn(ct, game) -> tuple[str, object]:
    """A-Stage 5: forage only. No split, no threat filter (workers take risks)."""
    safe_dirs = get_safe_directions(ct, game)
    choice = find_target_direction(ct, game, safe_dirs)
    if choice is None:
        choice = get_fallback_move(ct, game, safe_dirs)
    ct.make_move(choice)
    return "move", choice

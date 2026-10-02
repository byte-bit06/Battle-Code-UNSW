"""Stage 0 shared engine: the primitives every role builds on.

Every function here is stateless. It reads the current turn from `ct` / `game`
and returns a value; nothing is remembered between calls.
"""
from helper import Direction, EdgeType, Position, Team

QUEEN = "queen"
HUNTER = "hunter"
WORKER = "worker"


# ---------------------------------------------------------------- 0.1 Role detection

def _team_letter(team) -> str:
    """Accept either a helper Team or the plain letter 'A' / 'B'."""
    return team.value if isinstance(team, Team) else team


def get_queen_id(team) -> int:
    """The fixed queen ID for a team: 0 for Team A, 1 for Team B."""
    return 0 if _team_letter(team) == "A" else 1


def get_enemy_queen_id(team) -> int:
    """The queen ID of the other team."""
    return 1 if _team_letter(team) == "A" else 0


def get_role(dragon_id: int, team) -> str:
    """'queen', 'hunter' or 'worker'. Fixed for the dragon's lifetime."""
    queen_id = get_queen_id(team)
    if dragon_id == queen_id:
        return QUEEN
    # Phase 1: the queen's first split is the first new ID on the board,
    # and IDs are global, so it is queen_id + 2.
    if dragon_id == queen_id + 2:
        return HUNTER
    return WORKER


# ---------------------------------------------------------------- distance helpers

def toroidal_delta(a: int, b: int, size: int) -> int:
    """Signed shortest step count from a to b on a wrapping axis.
    An exact half-map tie resolves to the positive direction."""
    d = (b - a) % size
    if d > size // 2:
        d -= size
    return d


def toroidal_distance(p1: Position, p2: Position, width: int, height: int) -> int:
    """Manhattan distance on the torus."""
    dx = abs(p1.x - p2.x)
    dy = abs(p1.y - p2.y)
    return min(dx, width - dx) + min(dy, height - dy)


# ---------------------------------------------------------------- 0.3 Destination resolver

def resolve_destination(ct, pos: Position, direction: Direction) -> Position | None:
    """Where a head at `pos` lands after one step in `direction`.

    Empty edge  -> the adjacent tile, wrapped at the map border.
    Portal edge -> the tile just past the partner edge, same heading.
                   None if the partner edge is not in vision (unknown).
    Kelp edge   -> None (crossing it is death, there is no destination).
    None is also returned if `pos` itself is outside vision.
    """
    tile = ct.get_tile(pos)
    if tile is None:
        return None
    edge = tile.get_edge(direction)
    edge_type = edge.get_edge_type()

    if edge_type == EdgeType.KELP:
        return None
    if edge_type != EdgeType.PORTAL:
        return pos.add_dir(direction)

    portal_id = edge.get_portal_id()
    opposite = direction.get_opposite()
    entry_far_side = pos.add_dir(direction)
    for other in ct.get_tiles():
        other_pos = other.get_position()
        # `other` sits before the partner edge: we come out one step past it.
        if other_pos != pos:
            e = other.get_edge(direction)
            if e.get_edge_type() == EdgeType.PORTAL and e.get_portal_id() == portal_id:
                return other_pos.add_dir(direction)
        # `other` sits just past the partner edge: that is where we come out.
        if other_pos != entry_far_side:
            e = other.get_edge(opposite)
            if e.get_edge_type() == EdgeType.PORTAL and e.get_portal_id() == portal_id:
                return other_pos
    return None


# ---------------------------------------------------------------- 0.2 Safe move validator

def get_safe_directions(ct, game) -> list[Direction]:
    """Directions whose single step is certainly survivable right now.

    Blocked: kelp, any dragon segment (own neck, own tail, enemy head/body),
    and destinations we cannot see (portals whose far side is out of vision).
    The tail always counts as blocked: collision is checked before it moves.
    Order is the helper's N, E, S, W.
    """
    here = ct.get_position()
    if ct.get_tile(here) is None:
        return []
    safe = []
    for direction in Direction.get_direction_list():
        dest = resolve_destination(ct, here, direction)
        if dest is None:
            continue  # kelp, or a portal exit we cannot see
        if dest == here:
            continue  # stepping back onto ourselves
        dest_tile = ct.get_tile(dest)
        if dest_tile is None:
            continue  # outside vision: unknown, skip
        if dest_tile.get_dragon() is not None:
            continue  # any dragon segment blocks
        safe.append(direction)
    return safe


# ---------------------------------------------------------------- 0.4 Nearest pearl finder

def find_nearest_pearl(ct, game) -> Position | None:
    """Position of the visible pearl closest to the head by toroidal
    Manhattan distance, or None if no pearl is visible. Ties go to the
    first tile in vision order (top-left, row by row)."""
    here = ct.get_position()
    width, height = game.get_map_size()
    best, best_dist = None, None
    for tile in ct.get_tiles():
        if not tile.has_pearl():
            continue
        pos = tile.get_position()
        dist = toroidal_distance(here, pos, width, height)
        if best_dist is None or dist < best_dist:
            best, best_dist = pos, dist
    return best


# ---------------------------------------------------------------- 0.5 Direction toward target

def direction_toward(here: Position, target: Position, width: int, height: int,
                     safe_dirs: list[Direction] | None = None) -> Direction:
    """The cardinal direction along the dominant axis of the shortest
    toroidal route to `target`. Greedy: ignores obstacles.

    If target == here there is nowhere to go, so the first of `safe_dirs`
    is returned (or NORTH if none were given). Ties between axes go to
    the horizontal axis.
    """
    dx = toroidal_delta(here.x, target.x, width)
    dy = toroidal_delta(here.y, target.y, height)
    if dx == 0 and dy == 0:
        return safe_dirs[0] if safe_dirs else Direction.NORTH
    if abs(dx) >= abs(dy):
        return Direction.EAST if dx > 0 else Direction.WEST
    return Direction.SOUTH if dy > 0 else Direction.NORTH


# ---------------------------------------------------------------- 0.6 Fallback move

def get_fallback_move(ct, game, safe_dirs: list[Direction] | None = None) -> Direction:
    """Always returns a Direction, never None.

    1. The first safe direction, if any.
    2. Fully blocked: a step into an adjacent enemy head (head-on, so the
       enemy dies with us and drops pearls).
    3. A portal whose far side we cannot see: unknown beats certain death.
    4. NORTH.
    """
    if safe_dirs is None:
        safe_dirs = get_safe_directions(ct, game)
    if safe_dirs:
        return safe_dirs[0]

    here = ct.get_position()
    here_tile = ct.get_tile(here)
    if here_tile is None:
        return Direction.NORTH
    my_team = ct.get_team()

    for direction in Direction.get_direction_list():
        dest = resolve_destination(ct, here, direction)
        if dest is None:
            continue
        dest_tile = ct.get_tile(dest)
        if dest_tile is None:
            continue
        part = dest_tile.get_dragon()
        if part is not None and part.is_head() and part.get_team() != my_team:
            return direction

    for direction in Direction.get_direction_list():
        edge = here_tile.get_edge(direction)
        if edge.get_edge_type() == EdgeType.PORTAL and resolve_destination(ct, here, direction) is None:
            return direction

    return Direction.NORTH

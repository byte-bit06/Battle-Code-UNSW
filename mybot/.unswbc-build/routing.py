"""Space-time routing.

Own-body release rule: our segment at index i (head = 0, tail = L-1) blocks
its tile until the body has moved past it. With no pearls eaten, the tile is
enterable on move k only if  k > L - i.  (The tail cell is enterable from
move 2, never move 1, because collision is checked before movement.)
Segments of other dragons are permanent walls (worst-case tail assumption).

BFS only *proposes* paths. `simulate` is the authoritative check, because it
also models the tail staying put on turns we eat a pearl.
"""


class SimResult:
    __slots__ = ("body", "L", "eaten", "hidden")

    def __init__(self, body, L, eaten, hidden):
        self.body = body        # head first, visible/known segments only
        self.L = L              # length after the route
        self.eaten = eaten      # tiles eaten along the route, in order
        self.hidden = hidden    # segments beyond vision still attached to the tail


def bfs(geo, start, walls, own_index, L, node_cap, radius, deadline=None,
        seen_round=None, goal=-1, release=None):
    """Breadth-first search from `start`.

    Returns (dist, parent, unknown) dicts keyed by tile:
      dist[t]    moves needed
      parent[t]  (previous tile, direction)
      unknown[t] number of never-seen tiles on the path (if seen_round given)
    `release` maps some wall tiles (fully visible enemy dragons) to the move
    after which they become enterable: tile t is open on move k if k > release[t].
    Stops early when `goal` is reached, after `node_cap` expansions, or at `radius`.
    """
    dist = {start: 0}
    parent = {}
    unknown = {start: 0}
    queue = [start]
    qi = 0
    step_nb = geo.neighbours
    while qi < len(queue) and qi < node_cap:
        cur = queue[qi]
        qi += 1
        if deadline is not None and (qi & 63) == 0:
            deadline.check()
        k = dist[cur] + 1
        if k > radius:
            continue
        ucur = unknown[cur]
        nb = step_nb(cur)
        for d in (0, 1, 2, 3):
            n = nb[d]
            if n < 0 or n in dist:
                continue
            if n in walls:
                if release is None or k <= release.get(n, 10 ** 6):
                    continue
            oi = own_index.get(n)
            if oi is not None and k <= L - oi:
                continue
            dist[n] = k
            parent[n] = (cur, d)
            unknown[n] = ucur + (1 if seen_round is not None and seen_round[n] < 0 else 0)
            if n == goal:
                return dist, parent, unknown
            queue.append(n)
    return dist, parent, unknown


def path_to(parent, start, target):
    """Directions from start to target using a BFS parent map."""
    moves = []
    t = target
    while t != start:
        p = parent.get(t)
        if p is None:
            return None
        moves.append(p[1])
        t = p[0]
    moves.reverse()
    return moves


def simulate(geo, body, L, moves, pearls, walls, release=None):
    """Step the body along `moves`. Returns SimResult, or None on any collision.

    body   : head-first list of our known segments
    L      : true length (segments beyond `body` are hidden at the tail end)
    pearls : set of tiles holding pearls (not modified)
    """
    body = list(body)
    bodyset = set(body)
    hidden = L - len(body)
    eaten = []
    k = 0
    for d in moves:
        k += 1
        n = geo.step(body[0], d)
        if n < 0 or n in bodyset:
            return None
        if n in walls and (release is None or k <= release.get(n, 10 ** 6)):
            return None
        body.insert(0, n)
        bodyset.add(n)
        if n in pearls and n not in eaten:
            eaten.append(n)
            L += 1
        elif hidden > 0:
            hidden -= 1
        else:
            bodyset.discard(body.pop())
    return SimResult(body, L, eaten, hidden)


def flood_fill(geo, start, blocked, cap):
    """Number of tiles reachable from `start` (including it), capped at `cap`."""
    seen = {start}
    queue = [start]
    qi = 0
    step_nb = geo.neighbours
    while qi < len(queue):
        cur = queue[qi]
        qi += 1
        for n in step_nb(cur):
            if n < 0 or n in seen or n in blocked:
                continue
            seen.add(n)
            if len(seen) >= cap:
                return cap
            queue.append(n)
    return len(seen)


def timed_area(geo, body, L, blocked, cap):
    """Escape metric: tiles reachable from body[0] when our own segments free up
    over time (segment i frees after L-i moves), capped at `cap`.

    Unlike a static flood fill this understands tail-chasing: a dragon coiled in
    its own loop is fine as long as its tail keeps opening a way out.
    """
    own = {t: i for i, t in enumerate(body)}
    dist, _p, _u = bfs(geo, body[0], blocked, own, L, cap, cap)
    n = len(dist) - 1
    return n if n < cap else cap


def survives(geo, body, L, walls, depth, node_cap):
    """Is there ANY sequence of `depth` moves that doesn't collide?

    Exact body simulation (so tiles we newly occupy count), depth-first with a
    tail-chasing move order so open positions resolve in ~depth nodes.
    Returns True (proved), False (proved trapped) or None (node cap hit).
    Pearls are ignored on purpose: eating only makes the body longer.
    """
    budget = [node_cap]
    manhattan = geo.manhattan
    step_nb = geo.neighbours

    def dfs(body, bodyset, hidden, remaining):
        if remaining == 0:
            return True
        budget[0] -= 1
        if budget[0] < 0:
            return None
        nb = step_nb(body[0])
        tail = body[-1]
        opts = [n for n in nb if n >= 0 and n not in bodyset and n not in walls]
        if len(opts) > 1:
            opts.sort(key=lambda n: manhattan(n, tail))
        unknown = False
        for n in opts:
            nbody = [n] + body
            nset = set(bodyset)
            nset.add(n)
            if hidden > 0:
                r = dfs(nbody, nset, hidden - 1, remaining - 1)
            else:
                nset.discard(nbody.pop())
                r = dfs(nbody, nset, 0, remaining - 1)
            if r:
                return True
            if r is None:
                unknown = True
        return None if unknown else False

    body = list(body)
    return dfs(body, set(body), L - len(body), depth)

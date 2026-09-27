"""Forage Engine: decide how this dragon grows.

Stage 1  hard feasibility filter        -> is_feasible()
Stage 2  additive score S(i, p)         -> score_partial() + score_full()
Stage 3  death-drop scavenging          -> detect_clusters() + beam_scavenge()
Stage 4  predicted spawns (incl. mirror)-> build_predictive_candidates()
Stage 5  orchestration                  -> forage_turn()

    S(i,p) = R_i + B_cluster + B_timing
             - C_D*TravelCost - C_R*EnemyRisk - C_T*TrapRisk
             - C_S*SprintCost - C_U*Uncertainty

Budget note: everything here runs inside the judge's 100M-point turn budget,
so every search is capped (see config.py) and checks the deadline.
"""

import config
import routing

INF = float("inf")


class ForageTimeout(Exception):
    """Raised by Deadline.check(); main.py falls back to the emergency move."""


class Candidate:
    __slots__ = ("target", "kind", "moves", "first", "countdown", "uncertainty",
                 "sim", "score", "reject_reason", "reward", "dist", "sprint",
                 "contested", "timing", "unknown", "area")

    def __init__(self, target, kind, dist, reward, countdown=None, uncertainty=0.0, unknown=0):
        self.target = target
        self.kind = kind              # 'live' | 'predicted' | 'cluster'
        self.dist = dist              # moves to reach the target tile
        self.reward = reward          # R_i
        self.countdown = countdown    # T for 'predicted'
        self.uncertainty = uncertainty
        self.unknown = unknown        # never-seen tiles on the route
        self.moves = None
        self.first = None             # int direction, or list of ints for a sprint
        self.sim = None
        self.score = -INF
        self.reject_reason = ""
        self.sprint = 0               # SprintCost (segments spent)
        self.contested = False        # equal-ETA race we only win on turn order
        self.timing = 0.0             # B_timing
        self.area = 0                 # escape area after the route (EscapeCapacity)

    def __repr__(self):
        return (f"Candidate({self.kind}@{self.target} d={self.dist} S={self.score:.1f}"
                f"{' REJ:' + self.reject_reason if self.reject_reason else ''})")


class Ctx:
    """Per-turn shared data so helpers don't recompute it."""
    __slots__ = ("snap", "mem", "geo", "safe", "deadline", "dist", "parent", "unknown",
                 "pearls", "enemies", "now", "L", "threat_tiles", "step_area",
                 "careful", "big", "c_r", "c_t")


LAST_DEBUG = ""
LAST_TARGET = (None, None)    # (tile, distance) of this turn's plan, for CLAIM messages


# =========================================================== Stage 5 ======
def forage_turn(snap, mem, safe, deadline, kinds=None, fallback=True, c=None):
    """Return a list of directions (ints). [] only when `safe` is empty.

    HRL options call this with `kinds` (a subset of 'live', 'predicted',
    'cluster') to restrict the targets, and fallback=False to get None instead
    of an exploration step when no target qualifies. `c` reuses a Ctx already
    built this turn. With the defaults it never returns None.
    Only raises ForageTimeout.
    """
    global LAST_DEBUG, LAST_TARGET
    LAST_TARGET = (None, None)
    if not safe:
        return []
    if c is None:
        c = make_ctx(snap, mem, safe, deadline)
    geo = c.geo

    cands = []
    clusters = detect_clusters(c) if kinds is None or "cluster" in kinds else []
    for cluster in clusters:
        cc = beam_scavenge(c, cluster)
        if cc is not None:
            cands.append(cc)
    if kinds is None or "live" in kinds:
        cands += build_live_candidates(c)
    if (kinds is None and not clusters) or (kinds is not None and "predicted" in kinds):
        cands += build_predictive_candidates(c)     # save budget while scavenging

    # cheap score for everything, expensive checks only for the best few
    ranked = []
    for cand in cands:
        if score_partial(cand, c):
            ranked.append(cand)
    ranked.sort(key=lambda x: x.score, reverse=True)
    ranked = ranked[:config.MAX_CANDIDATES]

    best = None
    checked = 0
    try:
        for cand in ranked:
            if checked >= config.TOP_K_FLOODFILL:
                break
            deadline.check()
            checked += 1
            if not is_feasible(cand, c):
                continue
            score_full(cand, c)
            if best is None or cand.score > best.score:
                best = cand
    except ForageTimeout:
        if best is None:          # nothing verified yet: let main.py fall back
            raise

    if best is not None and best.score >= config.MIN_SCORE:
        LAST_TARGET = (best.target, best.dist)
        if config.DEBUG:
            LAST_DEBUG = f"F {best.kind}@{geo.xy(best.target)} S{best.score:.0f}"
        return list(best.first) if isinstance(best.first, list) else [best.first]
    if not fallback:
        return None
    late = deadline.remaining() < config.LATE_RESERVE_S   # keep the tail of the budget
    far = None if (late or not config.ENABLE_FAR_GOALS) else far_goal(c)
    if far is not None:
        return [far]
    if config.DEBUG:
        LAST_DEBUG = "EXPLORE"
    return [explore(c, use_goal=config.ENABLE_EXPLORE_GOAL and not late)]


def make_ctx(snap, mem, safe, deadline):
    """Per-turn shared data: one capped BFS from our head, known pearls,
    nearby heads and the tiles those heads could step onto next."""
    c = Ctx()
    c.snap, c.mem, c.geo, c.safe, c.deadline = snap, mem, mem.geo, safe, deadline
    c.now = snap.round
    c.L = snap.my_len
    c.dist, c.parent, c.unknown = routing.bfs(
        c.geo, snap.head, snap.walls, snap.own_index, c.L,
        config.BFS_NODE_CAP, config.BFS_RADIUS, deadline, mem.seen_round,
        release=snap.release)
    c.pearls = set(mem.pearls)
    c.pearls.update(snap.pearls)
    geo = c.geo
    c.enemies = [h for h in snap.heads if geo.manhattan(h.pos, snap.head) <= config.ENEMY_RADIUS]
    c.threat_tiles = set()
    for h in c.enemies:
        for n in geo.neighbours(h.pos):
            if n >= 0:
                c.threat_tiles.add(n)
    c.step_area = {}
    # tiebreak holder plays safe (only matters once teammates exist)
    c.careful = mem.is_longest(snap) and bool(getattr(mem, "best_len_heard", 0))
    mult = config.CAREFUL_RISK_MULT if c.careful else 1.0
    c.c_r = config.C_R * mult
    c.c_t = config.C_T * mult
    c.big = deadline.remaining() > config.SPARE_TIME_S
    return c


# ====================================================== candidates ========
def build_live_candidates(c):
    out = []
    dist, unknown = c.dist, c.unknown
    now = c.now
    mem_pearls = c.mem.pearls
    visible_now = set(c.snap.pearls)
    head = c.snap.head
    for p in c.pearls:
        if p == head or p not in dist:
            continue
        if p in visible_now:
            unc = 0.0
        else:
            unc = min(1.0, 0.05 * (now - mem_pearls.get(p, now)))
        out.append(Candidate(p, "live", dist[p], config.R_LIVE, None, unc, unknown.get(p, 0)))
    return out


def build_predictive_candidates(c):
    """Stage 4: tiles whose (seen, remembered or mirrored) countdown says a
    pearl will appear around the time we could get there."""
    out = []
    mem = c.mem
    now = c.now
    cd_val, cd_round, cd_src = mem.cd_val, mem.cd_round, mem.cd_src
    own_index = c.snap.own_index
    L = c.L
    pearls = c.pearls
    offset = config.SPAWN_EAT_OFFSET
    wmin, wmax = config.PRED_WAIT_MIN, config.PRED_WAIT_MAX
    unknown = c.unknown
    for t, d in c.dist.items():
        v = cd_val[t]
        if v is None or v < 1 or d == 0 or t in pearls:
            continue
        T = v - (now - cd_round[t])
        if T < 1:
            continue
        wait = T + offset - d
        if wait < wmin or wait > wmax:
            continue
        oi = own_index.get(t)
        if oi is not None and L - oi > T:
            continue           # our own body would still cover it at spawn time
        if cd_src[t] == 2:
            unc = 1.0
        elif cd_round[t] == now:
            unc = 0.2
        else:
            unc = 0.4
        out.append(Candidate(t, "predicted", d, config.R_PREDICTED, T, unc, unknown.get(t, 0)))
    return out


# ============================================================ Stage 2 =====
def timing_bonus(cand):
    """B_timing. Late arrival is a finite penalty, not -inf: the pearl stays
    until someone eats it, arriving late only exposes it to rivals."""
    if cand.kind != "predicted":
        return 0.0
    wait = cand.countdown + config.SPAWN_EAT_OFFSET - cand.dist
    if wait == 0:
        return config.TIMING_BONUS
    if wait > 0:
        return -config.TIMING_EARLY_PENALTY * wait
    return -config.TIMING_LATE_PENALTY * (-wait)


def contention(cand, c):
    """ContentionWin rule. Returns (ok, contested). Enemy distance uses
    Manhattan, a lower bound on its real distance (conservative for us)."""
    geo = c.geo
    my_id = c.snap.my_id
    eta = cand.dist
    if cand.kind == "predicted":
        eta = max(cand.dist, cand.countdown + config.SPAWN_EAT_OFFSET)
    if c.mem.claimed_by_other(cand.target, eta, c.now):
        return False, False       # a teammate announced it is closer
    contested = False
    for h in c.enemies:
        e = geo.manhattan(h.pos, cand.target)
        if e < eta:
            return False, False
        if e == eta:
            if my_id > h.id:        # they move first each round and win the race
                return False, False
            if c.careful and not h.teammate:
                return False, False   # tiebreak holder never races an enemy
            contested = True
    return True, contested


def head_threat(geo, h, t, turn):
    """Risk that head h reaches tile t by our move number `turn`.
    Normal moves: 1.0. Only by sprinting (up to visible_len-1 steps a turn): 0.3.
    Plus HEADING_RISK if t lies straight ahead of it (it tends to keep going).
    Teammates count TEAMMATE_RISK_FACTOR as much (they avoid our head too)."""
    e = geo.manhattan(h.pos, t)
    if e <= turn:
        r = 1.0
    elif e <= turn * max(0, h.visible_len - 1):
        r = 0.3
    else:
        r = 0.0
    if e <= config.HEADING_RAY:
        p = h.pos
        for _ in range(e):
            p = geo.step(p, h.dir)
            if p < 0:
                break
        if p == t:
            r += config.HEADING_RISK
    return r * config.TEAMMATE_RISK_FACTOR if h.teammate else r


def enemy_risk_at_target(cand, c):
    geo = c.geo
    risk = 0.0
    for h in c.enemies:
        risk += head_threat(geo, h, cand.target, cand.dist)
    return risk


def score_partial(cand, c):
    """Cheap part of S. Returns False if the candidate is already infeasible."""
    ok, contested = contention(cand, c)
    if not ok:
        cand.reject_reason = "ContentionWin"
        if cand.kind == "live" and cand.dist <= 4:
            try_sprint(cand, c)          # only a sprint could still win it
            return cand.sprint > 0
        return False
    cand.contested = contested
    cand.timing = timing_bonus(cand)
    unc = cand.uncertainty + config.UNKNOWN_STEP_UNCERTAINTY * cand.unknown
    risk = enemy_risk_at_target(cand, c) + (1.0 if contested else 0.0)
    cand.score = (cand.reward + cand.timing
                  - config.C_D * cand.dist
                  - c.c_r * risk
                  - config.C_U * unc)
    return True


def route_enemy_risk(cand, c):
    """EnemyRisk along the first moves of the route (per step k, 1-based)."""
    if not c.enemies or not cand.moves:
        return 1.0 if cand.contested else 0.0
    geo = c.geo
    risk = 1.0 if cand.contested else 0.0
    t = c.snap.head
    k = 0
    for d in cand.moves[:6]:
        t = geo.step(t, d)
        if t < 0:
            break
        k += 1
        turn = 1 if cand.sprint else k
        for h in c.enemies:
            risk += head_threat(geo, h, t, turn)
    return risk


def score_full(cand, c):
    """Full S(i,p) once the route has been simulated (Stage 1 passed)."""
    geo = c.geo
    sim = cand.sim
    extra = [p for p in sim.eaten if p != cand.target]
    b_cluster = config.PEARL_ON_ROUTE_VALUE * len(extra)
    near = 0
    for p in c.pearls:
        if p != cand.target and p not in sim.eaten and geo.manhattan(p, cand.target) <= 2:
            near += 1
    b_cluster += config.NEARBY_PEARL_VALUE * near
    L_final = sim.L
    trap = max(0.0, config.TRAP_SAFE_FACTOR * L_final - cand.area) / L_final
    unc = cand.uncertainty + config.UNKNOWN_STEP_UNCERTAINTY * cand.unknown
    cand.score = (cand.reward + b_cluster + cand.timing
                  - config.C_D * len(cand.moves)
                  - c.c_r * route_enemy_risk(cand, c)
                  - c.c_t * trap
                  - config.C_S * cand.sprint
                  - config.C_U * unc)
    return cand.score


def try_sprint(cand, c):
    """Sprint rule: only for a live pearl we would otherwise lose, only if
    NetGain = pearls eaten - (s-1) > 0 and L - (s-1) >= max(L_RESERVE_MIN, s+1)."""
    if c.careful:
        return                    # tiebreak holder never spends length
    moves = routing.path_to(c.parent, c.snap.head, cand.target)
    if not moves:
        return
    s = len(moves)
    L = c.L
    if s < 2 or L - (s - 1) < max(config.L_RESERVE_MIN, s + 1):
        return
    if moves[0] not in c.safe:
        return
    sim = routing.simulate(c.geo, c.snap.body, L, moves, c.pearls, c.snap.walls, c.snap.release)
    if sim is None or len(sim.eaten) - (s - 1) <= 0:
        return
    # a one-turn arrival beats anyone who needs 2+ turns, or 1 turn with a higher id
    geo = c.geo
    for h in c.enemies:
        e = geo.manhattan(h.pos, cand.target)
        if e < 1 or (e == 1 and c.snap.my_id > h.id):
            return
    cand.sprint = s - 1
    cand.moves = moves
    cand.first = list(moves)
    cand.reject_reason = ""
    unc = cand.uncertainty
    cand.score = (cand.reward - config.C_D * s - config.C_S * cand.sprint - config.C_U * unc)


# ============================================================ Stage 1 =====
def is_feasible(cand, c):
    """Ordered hard filter. On failure sets cand.reject_reason."""
    snap, geo = c.snap, c.geo
    L = c.L
    # build the move list
    if cand.moves is None:
        if cand.kind == "predicted":
            wait = cand.countdown + config.SPAWN_EAT_OFFSET - cand.dist
            if wait > 0:
                if cand.countdown <= (config.HOLD_MAX_BIG if c.big else config.HOLD_MAX):
                    cand.moves = timed_approach(c, cand.target, cand.countdown)
                    if cand.moves is None:
                        cand.reject_reason = "TimedApproach"
                        return False
                else:
                    path = routing.path_to(c.parent, snap.head, cand.target)
                    cand.moves = path[:-1] if path and len(path) > 1 else None
            else:
                cand.moves = routing.path_to(c.parent, snap.head, cand.target)
        else:
            cand.moves = routing.path_to(c.parent, snap.head, cand.target)
    if not cand.moves:
        cand.reject_reason = "LegalPath"
        return False
    if cand.first is None:
        cand.first = cand.moves[0]
    first = cand.first[0] if isinstance(cand.first, list) else cand.first

    # 1. LegalFirstMove
    if first not in c.safe:
        cand.reject_reason = "LegalFirstMove"
        return False
    # 1b. FirstStepEscape: the tile we step onto now must not be a pocket,
    #     even if other dragons' heads move next to it (routes can be blocked later).
    if not cand.sprint and first_step_area(c, first) < first_step_need(c):
        cand.reject_reason = "FirstStepEscape"
        return False
    # 2. LegalPath (no kelp, no unknown portal anywhere on the route)
    t = snap.head
    for d in cand.moves:
        t = geo.step(t, d)
        if t < 0:
            cand.reject_reason = "LegalPath"
            return False
    # 3. SurvivalMargin (authoritative body simulation)
    sim = cand.sim or routing.simulate(geo, snap.body, L, cand.moves, c.pearls, snap.walls, snap.release)
    if sim is None:
        cand.reject_reason = "SurvivalMargin"
        return False
    cand.sim = sim
    # 4. ContentionWin was applied in score_partial (needs no route).
    # 5. TimedApproach handled while building moves.
    # 6. EscapeCapacity
    area = escape_area(geo, sim, snap.walls)
    cand.area = area
    need = min(sim.L + 1, config.FLOOD_CAP_MAX - 1)
    if c.careful:
        need = min(int(need * config.CAREFUL_ESCAPE_FACTOR), config.FLOOD_CAP_MAX - 1)
    if area < need:
        cand.reject_reason = "EscapeCapacity"
        return False
    return True


def first_step_need(c):
    return min(c.L + 1, config.FLOOD_CAP_MAX - 1, int(config.TRAP_SAFE_FACTOR * c.L) + 1)


def first_step_area(c, d):
    """Open tiles reachable after moving one step in direction d, with our body
    shifted and every tile another head could reach next turn blocked."""
    a = c.step_area.get(d)
    if a is not None:
        return a
    geo, snap = c.geo, c.snap
    n = geo.step(snap.head, d)
    sim = routing.simulate(geo, snap.body, c.L, [d], c.pearls, snap.walls)
    if sim is None:
        c.step_area[d] = -1
        return -1
    blocked = snap.walls | c.threat_tiles
    blocked.discard(n)
    cap = min(config.FLOOD_CAP_MAX, int(config.TRAP_SAFE_FACTOR * sim.L) + 2)
    a = routing.timed_area(geo, sim.body, sim.L, blocked, cap)
    a = confirm_escape(geo, sim, snap.walls, a)
    c.step_area[d] = a
    return a


def confirm_escape(geo, sim, walls, area):
    """In tight spaces the BFS area is optimistic (it ignores tiles we newly
    occupy), so confirm with an exact survival search. Proven trapped -> -1,
    undecided -> just below the requirement."""
    if area >= 2 * sim.L or area >= config.FLOOD_CAP_MAX:
        return area
    depth = min(sim.L + 1, config.SURVIVE_DEPTH_MAX)
    ok = routing.survives(geo, sim.body, sim.L, walls, depth, config.SURVIVE_NODE_CAP)
    if ok is False:
        return -1
    if ok is None:
        return min(area, min(sim.L + 1, config.FLOOD_CAP_MAX - 1) - 1)
    return area


def escape_area(geo, sim, walls):
    """Tiles reachable from the final head (time-aware, tail frees as we move)."""
    cap = min(config.FLOOD_CAP_MAX, int(config.TRAP_SAFE_FACTOR * sim.L) + 2)
    return confirm_escape(geo, sim, walls, routing.timed_area(geo, sim.body, sim.L, walls, cap))


def timed_approach(c, target, T):
    """Exactly-timed approach for a predicted spawn (corrects the plan's
    'step on at T=1' off-by-one).

    Find T moves after which the head is adjacent to `target` and no body
    segment covers it (so the spawn succeeds), then add the move onto it
    (move T + SPAWN_EAT_OFFSET). Bounded DFS; returns None if none found.
    """
    geo = c.geo
    snap = c.snap
    walls = snap.walls
    pearls = c.pearls
    deadline = c.deadline
    budget = [config.HOLD_NODE_CAP]
    manhattan = geo.manhattan

    def dfs(body, bodyset, hidden, L, remaining, moves):
        budget[0] -= 1
        if budget[0] < 0:
            return None
        if (budget[0] & 31) == 0:
            deadline.check()
        head = body[0]
        if remaining == 0:
            if target in bodyset:
                return None
            nb = geo.neighbours(head)
            for d in (0, 1, 2, 3):
                if nb[d] == target:
                    return moves + [d]
            return None
        if manhattan(head, target) - 1 > remaining:
            return None
        nb = geo.neighbours(head)
        order = sorted((0, 1, 2, 3), key=lambda d: -manhattan(nb[d], target) if nb[d] >= 0 else 99)
        for d in order:
            n = nb[d]
            if n < 0 or n in bodyset or n in walls:
                continue
            if not moves and d not in c.safe:
                continue
            nbody = [n] + body
            nset = set(bodyset)
            nset.add(n)
            nh, nL = hidden, L
            if n in pearls and n != target:
                nL += 1
            elif nh > 0:
                nh -= 1
            else:
                nset.discard(nbody.pop())
            r = dfs(nbody, nset, nh, nL, remaining - 1, moves + [d])
            if r is not None:
                return r
        return None

    body = list(snap.body)
    return dfs(body, set(body), c.L - len(body), c.L, T, [])


# ============================================================ Stage 3 =====
def detect_clusters(c):
    """Groups of >= SCAVENGE_MIN_PEARLS pearls near us, linked when their
    Manhattan distance is <= 2 (death drops sit on every second segment)."""
    geo = c.geo
    head = c.snap.head
    near = [p for p in c.pearls if geo.manhattan(p, head) <= config.SCAVENGE_RADIUS]
    if len(near) < config.SCAVENGE_MIN_PEARLS:
        return []
    groups = []
    unassigned = set(near)
    while unassigned:
        seed = unassigned.pop()
        group = [seed]
        stack = [seed]
        while stack:
            a = stack.pop()
            linked = [b for b in unassigned if geo.manhattan(a, b) <= 2]
            for b in linked:
                unassigned.discard(b)
                group.append(b)
                stack.append(b)
        if len(group) >= config.SCAVENGE_MIN_PEARLS:
            groups.append(group)
    return groups


def beam_scavenge(c, cluster):
    """Small beam search over pickup orders. Paths are recomputed on each
    state's simulated body, because eating stops the tail from advancing."""
    geo, snap, deadline = c.geo, c.snap, c.deadline
    walls = snap.walls
    # state: (rank, body, L, remaining_set, moves, eaten)
    start = (0.0, list(snap.body), c.L, set(cluster), [], 0)
    beam = [start]
    best = None
    expansions = 0
    width = config.BEAM_WIDTH_BIG if c.big else config.BEAM_WIDTH
    horizon = config.BEAM_HORIZON_BIG if c.big else config.BEAM_HORIZON
    cap = config.BEAM_EXPANSION_CAP_BIG if c.big else config.BEAM_EXPANSION_CAP
    for _ in range(horizon):
        nxt = []
        for (_, body, L, remaining, moves, eaten) in beam:
            head = body[0]
            options = sorted(remaining, key=lambda p: geo.manhattan(head, p))[:3]
            own = {t: i for i, t in enumerate(body)}
            for p in options:
                expansions += 1
                if expansions > cap:
                    break
                deadline.check()
                dist, parent, _u = routing.bfs(geo, head, walls, own, L, config.LOCAL_BFS_CAP,
                                               config.SCAVENGE_RADIUS * 2, None, None, p,
                                               release=snap.release)
                if p not in dist:
                    continue
                seg = routing.path_to(parent, head, p)
                if not seg or (not moves and seg[0] not in c.safe):
                    continue
                sim = routing.simulate(geo, body, L, seg, remaining, walls)
                if sim is None:
                    continue
                rem = remaining - set(sim.eaten)
                tot_moves = moves + seg
                tot_eaten = eaten + len(sim.eaten)
                rank = tot_eaten - 0.1 * len(tot_moves)
                nxt.append((rank, sim.body, sim.L, rem, tot_moves, tot_eaten))
        if not nxt:
            break
        nxt.sort(key=lambda s: s[0], reverse=True)
        beam = nxt[:width]
        for st in beam:
            if best is None or st[0] > best[0]:
                # final state must keep an escape route on the grown body
                sim = routing.SimResult(st[1], st[2], [], 0)
                if escape_area(geo, sim, walls) >= min(st[2] + 1, config.FLOOD_CAP_MAX - 1):
                    best = st
        if expansions > cap:
            break
    if best is None or best[5] < 1:
        return None
    moves = best[4]
    t = snap.head
    for d in moves:
        t = geo.step(t, d)
    cand = Candidate(t, "cluster", len(moves), config.R_LIVE * best[5])
    cand.moves = moves
    cand.first = moves[0]
    return cand


# ========================================================== long range ====
def frontier_step(c, goal):
    """First move toward a goal outside the BFS radius: head for the reached
    tile f minimising dist[f] + manhattan(f, goal). Returns (direction, eta) or (None, None)."""
    geo = c.geo
    head = c.snap.head
    best_f, best_v = None, None
    for f, d in c.dist.items():
        if d == 0:
            continue
        v = d + geo.manhattan(f, goal)
        if best_v is None or v < best_v or (v == best_v and d < c.dist[best_f]):
            best_f, best_v = f, v
    if best_f is None:
        return None, None
    path = routing.path_to(c.parent, head, best_f)
    return (path[0], best_v) if path else (None, None)


def far_goal(c):
    """No worthwhile local target: aim for remembered pearls beyond the BFS
    radius or death drops / clusters teammates reported over sonar."""
    global LAST_TARGET, LAST_DEBUG
    geo, mem, now, head = c.geo, c.mem, c.now, c.snap.head
    options = []
    for p, r in mem.pearls.items():
        if p in c.dist:
            continue
        m = geo.manhattan(p, head)
        if m <= config.FAR_GOAL_RADIUS:
            options.append((p, config.R_LIVE, min(1.0, 0.05 * (now - r)), m))
    for t, (count, r, _kind) in mem.reports.items():
        m = geo.manhattan(t, head)
        if m <= config.FAR_GOAL_RADIUS:
            options.append((t, config.R_REPORTED_PEARL * count, 0.5 + 0.02 * (now - r), m))
    best, best_s = None, config.FAR_MIN_SCORE
    for t, reward, unc, m in options:
        if mem.claimed_by_other(t, m, now):
            continue
        s = reward - config.C_D * m - config.C_U * unc
        for e, (r, _l) in mem.enemy_reports.items():
            if now - r <= 5 and geo.manhattan(e, t) <= 3:
                s -= c.c_r
                break
        if s > best_s:
            best, best_s = t, s
    if best is None:
        return None
    d, eta = frontier_step(c, best)
    if d is None or d not in c.safe or first_step_area(c, d) < first_step_need(c):
        return None
    LAST_TARGET = (best, eta)
    if config.DEBUG:
        LAST_DEBUG = f"FAR@{geo.xy(best)} S{best_s:.0f}"
    return d


def explore_goal(c):
    """Pick (and keep for a while) the stalest 8x8 block, weighted by distance."""
    mem, geo, now, head = c.mem, c.geo, c.now, c.snap.head
    B = config.EXPLORE_BLOCK
    g = mem.explore_goal
    if g is not None:
        t, since = g
        bx, by = (t % mem.W) // B, (t // mem.W) // B
        if now - since <= config.EXPLORE_GOAL_KEEP and mem.block_seen[by * mem.nbx + bx] < since:
            return t
    best, best_s = None, None
    nby = len(mem.block_seen) // mem.nbx
    for by in range(nby):
        for bx in range(mem.nbx):
            seen = mem.block_seen[by * mem.nbx + bx]
            stale = (now + 50) if seen < 0 else now - seen
            cx = min(bx * B + B // 2, mem.W - 1)
            cy = min(by * B + B // 2, mem.H - 1)
            t = cy * mem.W + cx
            s = stale - 2 * geo.manhattan(t, head)
            if best_s is None or s > best_s:
                best, best_s = t, s
    mem.explore_goal = (best, now)
    return best


# ============================================================= explore ====
def explore(c, use_goal=True):
    """Guaranteed-legal fallback: open space first, then unexplored ground,
    with a little momentum so we don't dither. Always returns an element of safe."""
    geo, snap = c.geo, c.snap
    seen = c.mem.seen_round
    now = c.now
    best_d, best_s = c.safe[0], -INF
    need = first_step_need(c)
    goal = explore_goal(c) if use_goal else None
    goal_dir = frontier_step(c, goal)[0] if goal is not None else None
    for d in c.safe:
        n = geo.step(snap.head, d)
        area = first_step_area(c, d)
        if area < need:
            area -= 1000          # pockets only when nothing else exists
        stale = 0
        t = n
        for _ in range(5):
            t = geo.step(t, d)
            if t < 0:
                break
            r = seen[t]
            if r < 0 or now - r > 25:
                stale += 1
        s = area + config.EXPLORE_STALE_BONUS * stale
        if d == snap.my_dir:
            s += config.EXPLORE_MOMENTUM_BONUS
        if d == goal_dir:
            s += config.EXPLORE_GOAL_BONUS
        if s > best_s:
            best_d, best_s = d, s
    return best_d

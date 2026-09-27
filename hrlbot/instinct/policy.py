"""Move ranking, trade policy and the defensive split (4.6, 4.8, section 5).

The lexicographic key is the whole ranking:

    (tier_a_safe, -sprint_cost, options, R_tail, pearl_utility)

What survived measurement on the shipped path, against a control, on two board
types: a legality filter, and a count of the legal moves left after the step.
ram_exposure and corridor_count both COST survivals as ranking terms (chamber
34 -> 28, open 21 -> 20) and were deleted from the key. ram still shapes
l0_reflex and the tight hint, where it is nearly free; corridor_count still
gates the defensive split. See instinct_tests/MEASUREMENT.md.

`options` (how many legal moves we still have after the step) replaces the doc's
timed_space. MEASURED: timed_space was negative in every configuration (its cap
saturates on open boards) and it was the second most expensive term, while
`options` is free - tier_a_safe already enumerates those moves - and it is the
whole of what the five-line greedy control does better than this engine: apply a
"do not reduce your own options" cost on EVERY turn, not once danger is acute.

escape_depth (doc 4.2) is GONE: it saturated at the horizon we can afford,
appeared in nothing else, and ablated to no change. free_volume reads the same
joint envelope and does discriminate.

ram_exposure and corridor_count sit above volume on purpose: a wide-open tile
with two enemy heads covering it is worse than a narrow one with none.
"""

import config
import routing
from instinct import corridors, space, tempo
from instinct.state import State, TIER_A


def after_move(st, moves, tier=TIER_A):
    """The board as it would be after we play `moves`. None if we die."""
    sim = space.walk(st, moves, tier)
    if sim is None:
        return None
    nxt = State(st.geo, st.my_id, sim.body[0], sim.body, sim.L, st.enemies,
                st.allies, st.pearls - set(sim.eaten), st.seen_round,
                st.round + 1, longest_ally=st.longest_ally)
    return nxt


def legal_moves(st, tier=TIER_A):
    """One-step moves that don't walk into kelp or a body (our tail included:
    collision is checked before movement)."""
    out = []
    for d in (0, 1, 2, 3):
        if space.walk(st, [d], tier) is not None:
            out.append(d)
    return out


def tier_a_safe(st_after, tier=TIER_A):
    """Survives the worst case for one more round: some legal follow-up exists
    even if no other body ever vacates."""
    if st_after is None:
        return False
    return bool(legal_moves(st_after, tier))


def move_key(st, moves, tier=TIER_A, tight=False):
    """The lexicographic key for one candidate action (section 5).

    Cost control (measured on the judge, see config): the corridor count and the
    control layer are BFS-heavy, so L1 runs with neither and L2 pays for both.
    Terms that are skipped score 0, which keeps the tuple shape and the order.
    """
    nxt = after_move(st, moves, tier)
    if nxt is None:
        return (False, -99, 0, 0, 0)
    legal_after = legal_moves(nxt, tier)      # computed once: safety AND options
    safe = bool(legal_after)
    options = len(legal_after)
    sprint_cost = len(moves) - 1
    r_tail = max(0, nxt.L - 15) * 50
    # Under Instinct a pearl in tight space is a cost, not a reward: it is forced
    # growth inside a shrinking room. Flip the sign so Forage's appetite cannot
    # walk us onto it (4.5).
    eaten = nxt.L - st.L
    if tight:                             # forced growth in a tight space is a cost
        eaten = -eaten
    if "options" in config.INSTINCT_ABLATE:      # does the term earn its place?
        options = 0
    return (safe, -sprint_cost, options, r_tail, eaten)


def best_move(st, candidates=None, tier=TIER_A, tight=False):
    """Highest key wins; None when nothing is legal."""
    cands = candidates if candidates is not None else [[d] for d in (0, 1, 2, 3)]
    best, best_key = None, None
    for moves in cands:
        k = move_key(st, moves, tier, tight)
        if not k[0] and best_key is not None and best_key[0]:
            continue
        if best_key is None or k > best_key:
            best, best_key = moves, k
    return best, best_key


# ----------------------------------------------------------------- trade --
def may_trade(st, enemy):
    """Who may accept a head-to-head (4.6). A trade kills both dragons."""
    if st.longest_ally:
        return False                      # the tiebreak holder never trades
    if st.L <= 3:
        return True                       # we drop 1 pearl, they drop ceil(L/2)
    longest_enemy = max((d.length for d in st.enemies), default=0)
    if enemy.length >= st.L + 4:
        return True
    # "or the enemy is their longest dragon" (4.6). Read literally that trades a
    # length-30 dragon for a length-2 one whenever only one enemy is visible, so
    # their longest also has to be worth at least what we are giving up.
    return enemy.length >= longest_enemy and enemy.length >= st.L


# ----------------------------------------------------------------- split --
def split_legality(st, k, unit_count=1):
    """Engine rules only: child k >= 2, parent >= 2 after, team < 64.
    An illegal split kills the parent, so this gate is hard."""
    return st.L >= 4 and k >= 2 and st.L - k >= 2 and unit_count < 64


def should_split(st, k=None, unit_count=1, tier=TIER_A, control=None):
    """The defensive split (4.8): boxed in, but nobody can hit us this round.
    Splitting forfeits the move, so it is only safe with zero ram exposure."""
    if not config.INSTINCT_DEFENSIVE_SPLIT:
        return None
    k = max(2, st.L // 2) if k is None else k
    if not split_legality(st, k, unit_count):
        return None
    if corridors.corridor_count(st, tier=tier) > 1:
        return None
    if space.timed_space(st, tier) >= st.L:
        return None
    if tempo.ram_exposure(st, st.head, tier) > 0:
        return None
    if len(st.body) < st.L:
        return None                        # body not fully known: don't gamble
    parent_body, child_body = st.body[:st.L - k], st.body[st.L - k:][::-1]
    a_head = _area(st, parent_body, tier)
    a_tail = _area(st, child_body, tier)
    if a_head < st.L - k or a_tail < k:
        return None
    return k


def _area(st, body, tier):
    blocked = st.blocked(tier, include_own=False) | set(body[1:])
    return routing.flood_fill(st.geo, body[0], blocked, config.INSTINCT_REGION_CAP)

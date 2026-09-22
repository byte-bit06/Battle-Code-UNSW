"""Minimal safety layer.

INTERFACE FROZEN - the Defence team (branch Defence_Engine) will replace the
internals of these functions, but the signatures and return types must stay:

    classify_moves(snap, mem) -> (safe: list[int], risky: list[int])
                                 (+ classify_all -> (safe, risky, gamble))
    get_safe_moves(snap, mem) -> list[int]
    emergency_move(snap, mem, safe) -> int     # always a direction

Directions are ints: 0 N, 1 E, 2 S, 3 W.
"""


def classify_moves(snap, mem):
    safe, risky, _gamble = classify_all(snap, mem)
    return safe, risky


def classify_all(snap, mem):
    """safe   : legal, nothing dangerous next to it
    risky  : legal, but next to a head that moves after us this round
    gamble : legal, but we can't see where it leads (portal to an unseen or
             unknown exit). Taken only when nothing else is legal."""
    geo = mem.geo
    head = snap.head
    occ = snap.occ
    visible = snap.visible
    # heads that have not moved yet this round can still step next to us
    threats = [h.pos for h in snap.heads if h.id > snap.my_id]
    safe, risky, gamble = [], [], []
    for d in (0, 1, 2, 3):
        n = geo.step(head, d)
        if n == -1:               # kelp: certain death
            continue
        if n == -2 or n not in visible:
            gamble.append(d)      # portal to somewhere we can't see
            continue
        if n in occ:              # any segment, including our own tail
            continue
        danger = False
        for t in threats:
            if n in geo.neighbours(t):
                danger = True
                break
        (risky if danger else safe).append(d)
    return safe, risky, gamble


def get_safe_moves(snap, mem):
    """Best available class of legal moves. Empty ONLY when every direction is
    certain death (kelp, a body segment or a head)."""
    safe, risky, gamble = classify_all(snap, mem)
    return safe or risky or gamble


def emergency_move(snap, mem, safe):
    """Always returns a direction. Preference: a safe move, then any move that
    is not kelp and not onto a body segment, then any non-kelp move, then N."""
    if safe:
        return safe[0]
    geo = mem.geo
    head = snap.head
    non_kelp = []
    for d in (0, 1, 2, 3):
        n = geo.step(head, d)
        if n == -1:
            continue
        non_kelp.append(d)
        if n >= 0:
            o = snap.occ.get(n)
            if o is None:
                return d
    # every open tile holds a segment: prefer a head (mutual kill drops their pearls)
    for d in non_kelp:
        n = geo.step(head, d)
        o = snap.occ.get(n) if n >= 0 else None
        if o is not None and o[1] and not o[2]:
            return d
    return non_kelp[0] if non_kelp else 0

"""Dragon-to-dragon communication over sonar.

How sonar works (engine rules):
  * Once per turn a dragon may send ONE unsigned 32-bit integer.
  * After the dragon's action, the signal leaves its head in the direction it
    now FACES, wraps around the map, passes through portals, and stops at the
    first kelp edge or dragon segment. That dragon (any team, possibly the
    sender itself) receives it at the start of its next turn.
  * No sender id or team is attached, and enemies can hear us too.
So messages are best-effort broadcasts: we never know who will hear them.

Message layout (32 bits):
    [ type:4 | x:6 | y:6 | payload:8 | check:8 ]
  x, y fit maps up to 64x64. `check` is a keyed hash of the other 24 bits, so
  random numbers from other teams are rejected (about 1 in 256 slips through;
  every message is advisory, so a bad one can never make a move illegal).

Types:
  SYM     payload = symmetry code (1 V, 2 H, 3 R); x, y unused
  DEATH   a dragon just died here: payload = pearls seen appearing
  CLUSTER known group of pearls centred at (x, y): payload = count
  CLAIM   "I'm going for the pearl at (x, y)": payload = my distance to it
  LENGTH  heartbeat: payload = my length (capped at 255)
  ENEMY   enemy head at (x, y): payload = its visible length
"""

import config

T_SYM, T_DEATH, T_CLUSTER, T_CLAIM, T_LENGTH, T_ENEMY = 1, 2, 3, 4, 5, 6
SYM_CODE = {"V": 1, "H": 2, "R": 3}
CODE_SYM = {1: "V", 2: "H", 3: "R"}
KEY = 0x5A


def _check(body24: int) -> int:
    return (((body24 * 2654435761) & 0xFFFFFFFF) >> 24 ^ KEY) & 0xFF


def encode(kind: int, x: int, y: int, payload: int) -> int:
    payload = max(0, min(255, payload))
    body = ((kind & 0xF) << 20) | ((x & 0x3F) << 14) | ((y & 0x3F) << 8) | payload
    return (body << 8) | _check(body)


def decode(value: int):
    """Returns (kind, x, y, payload) or None if it isn't one of ours."""
    if not isinstance(value, int) or value < 0 or value > 0xFFFFFFFF:
        return None
    body = value >> 8
    if value & 0xFF != _check(body):
        return None
    kind = body >> 20
    if kind < T_SYM or kind > T_ENEMY:
        return None
    return kind, (body >> 14) & 0x3F, (body >> 8) & 0x3F, body & 0xFF


class Comms:
    """Per-dragon inbox/outbox state. Lives for the dragon's lifetime."""

    __slots__ = ("sym_sent_round", "sent_deaths", "rr", "stats_heard", "stats_sent")

    def __init__(self):
        self.sym_sent_round = -10 ** 6
        self.sent_deaths = {}      # tile -> round we broadcast it
        self.rr = 0                # round-robin index for low-priority messages
        self.stats_heard = 0
        self.stats_sent = 0

    # ------------------------------------------------------------ receive --
    def receive(self, messages, snap, mem):
        """Fold teammates' reports into memory. Everything is advisory."""
        now = snap.round
        W, H = mem.W, mem.H
        geo = mem.geo
        for raw in messages:
            msg = decode(raw)
            if msg is None:
                continue
            kind, x, y, payload = msg
            if x >= W or y >= H:
                continue
            self.stats_heard += 1
            t = geo.idx(x, y)
            if kind == T_SYM:
                hyp = CODE_SYM.get(payload)
                if hyp is not None:
                    mem.sym.accept_report(hyp)
            elif kind == T_DEATH or kind == T_CLUSTER:
                if t not in snap.visible:          # our own eyes beat hearsay
                    mem.reports[t] = (payload, now, kind)
            elif kind == T_CLAIM:
                mem.claims[t] = (now, payload)
            elif kind == T_LENGTH:
                if payload > mem.best_len_heard or now - mem.best_len_round > config.LONGEST_MEMORY_ROUNDS:
                    mem.best_len_heard = payload
                    mem.best_len_round = now
                elif payload == mem.best_len_heard:
                    mem.best_len_round = now
            elif kind == T_ENEMY:
                mem.enemy_reports[t] = (now, payload)

    # --------------------------------------------------------------- send --
    def choose(self, snap, mem, target, target_dist, deaths_seen):
        """Pick at most one message for this turn (or None)."""
        now = snap.round
        geo = mem.geo
        # 1. freshly observed deaths: time critical, the pearls go fast
        for t, count in deaths_seen:
            if now - self.sent_deaths.get(t, -99) > 5:
                self.sent_deaths[t] = now
                x, y = geo.xy(t)
                return encode(T_DEATH, x, y, count)
        # 2. symmetry, once locked, re-announced now and then for new children
        hyp = mem.sym.locked()
        if hyp is not None and now - self.sym_sent_round >= config.SYM_RESEND_ROUNDS:
            self.sym_sent_round = now
            return encode(T_SYM, 0, 0, SYM_CODE[hyp])
        # 3. rotate the rest so none of them starves
        options = []
        if target is not None and target_dist is not None and target_dist >= 2:
            x, y = geo.xy(target)
            options.append(encode(T_CLAIM, x, y, target_dist))
        options.append(encode(T_LENGTH, 0, 0, snap.my_len))
        cl = mem.best_cluster(snap)
        if cl is not None:
            (t, count) = cl
            x, y = geo.xy(t)
            options.append(encode(T_CLUSTER, x, y, count))
        enemies = [h for h in snap.heads if not h.teammate]
        if enemies:
            h = enemies[0]
            x, y = geo.xy(h.pos)
            options.append(encode(T_ENEMY, x, y, h.visible_len))
        self.rr = (self.rr + 1) % len(options)
        return options[self.rr]

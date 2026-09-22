"""One-off engine experiment (Section 5.3 of the prompt). NOT for submission.

Run:  unswbc run -v --no-replay maps/default.map probe_bot probe_bot
Logs to stderr:
  STEP  ok/bad   geometry.step prediction vs where the head really went
  PORTAL ok/bad  same, only for moves that crossed a portal
  SPAWNOBS       a countdown-1 empty tile last turn: is there a pearl now?
  RUN_A          stepped ONTO a countdown-1 tile; did we grow next turn?
  RUN_B          stayed ADJACENT at countdown 1, stepped on next turn; grew?
  SPLIT          head position / length before and after a split action
"""
import sys

import helper as unswbc
from helper import Direction

import forage
import memory
import safety
import snapshot

DIRS = Direction.get_direction_list()
DIR_INDEX = {d: i for i, d in enumerate(DIRS)}
ct = game = MEM = None
state = {"prev_head": None, "prev_d": None, "watch": [], "run": None, "split_at": None}


def log(msg):
    sys.stderr.write(msg + "\n")


class NoDeadline:
    def check(self):
        pass


def finish(snap, act):
    state["prev_head"] = snap.head
    state["prev_d"] = act[0] if len(act) == 1 else None
    if len(act) == 1:
        ct.make_move(DIRS[act[0]])
    else:
        ct.make_moves([DIRS[d] for d in act])


def turn():
    snap = snapshot.build(ct, game, MEM.geo, DIR_INDEX)
    MEM.update(snap)
    geo = MEM.geo
    st = state
    now = snap.round

    if st["prev_head"] is not None and st["prev_d"] is not None:
        pred = geo.step(st["prev_head"], st["prev_d"])
        ok = pred == snap.head
        tag = "PORTAL" if geo.is_portal(st["prev_head"], st["prev_d"]) else "STEP"
        log(f"{tag} {'ok' if ok else 'bad'} from {geo.xy(st['prev_head'])} d{st['prev_d']} "
            f"pred {geo.xy(pred) if pred >= 0 else pred} actual {geo.xy(snap.head)}")
    if st["split_at"] is not None:
        head0, len0 = st["split_at"]
        log(f"SPLIT before {geo.xy(head0)} len {len0} -> after {geo.xy(snap.head)} len {snap.my_len}")
        st["split_at"] = None

    for t in st["watch"]:
        if t in snap.visible:
            log(f"SPAWNOBS tile {geo.xy(t)} cd1 last turn -> pearl now {t in snap.pearls} "
                f"occupied {t in snap.occ} cd now {snap.countdowns[t]}")
    st["watch"] = [t for t, c in snap.countdowns.items()
                   if c == 1 and t not in snap.occ and t not in snap.pearls]

    if st["run"] is not None:
        kind, t, L0 = st["run"]
        st["run"] = None
        if kind == "A":
            log(f"RUN_A stepped onto cd1 tile {geo.xy(t)}: len {L0} -> {snap.my_len} (grew={snap.my_len > L0})")
        elif kind == "B1":
            if t in snap.pearls and t not in snap.occ:
                for d in range(4):
                    if geo.step(snap.head, d) == t:
                        st["run"] = ("B2", t, snap.my_len)
                        return finish(snap, [d])
            log(f"RUN_B pearl missing at {geo.xy(t)} (pearl={t in snap.pearls})")
        elif kind == "B2":
            log(f"RUN_B stepped on next turn {geo.xy(t)}: len {L0} -> {snap.my_len} (grew={snap.my_len > L0})")

    safe = safety.get_safe_moves(snap, MEM)

    if now == 15 and snap.my_len >= 4 and ct.can_split(2):
        st["split_at"] = (snap.head, snap.my_len)
        st["prev_head"], st["prev_d"] = snap.head, None
        ct.do_split(2)
        return

    if st["run"] is None:
        for d in safe:
            n = geo.step(snap.head, d)
            if snap.countdowns.get(n) == 1 and n not in snap.pearls:
                if now % 2 == 0:
                    st["run"] = ("A", n, snap.my_len)
                    return finish(snap, [d])
        if now % 2 == 1:
            # B: a countdown-1 tile two steps away -> become adjacent now, step on next turn
            for d2 in safe:
                m = geo.step(snap.head, d2)
                for n in geo.neighbours(m):
                    if n >= 0 and n != snap.head and n not in snap.occ and \
                            snap.countdowns.get(n) == 1 and n not in snap.pearls:
                        st["run"] = ("B1", n, snap.my_len)
                        return finish(snap, [d2])
    try:
        act = forage.forage_turn(snap, MEM, safe, NoDeadline()) or [safety.emergency_move(snap, MEM, safe)]
    except Exception:
        act = [safety.emergency_move(snap, MEM, safe)]
    finish(snap, act)


def main():
    global ct, game, MEM
    ct, game = unswbc.init()
    MEM = memory.WorldMemory(game.width, game.height)
    while unswbc.update(ct, game):
        try:
            turn()
        except Exception:
            import traceback
            log("EXC " + traceback.format_exc())
            ct.make_move(ct.get_dir())
        unswbc.end_turn()


main()

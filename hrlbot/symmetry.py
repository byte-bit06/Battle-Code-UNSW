"""Infer the map's symmetry (V, H or R) from what we observe.

Map files label symmetry as "y" (mirror x -> W-1-x, our 'V'), "x" (mirror
y -> H-1-y, our 'H') and "xy" (180 degree rotation, our 'R').

Evidence used:
  * Mirror tiles share one pearl countdown, so a countdown seen at p must
    match the countdown at mirror(p) whenever no reset could have happened
    in between. Never-spawning tiles (-1) must mirror onto -1.
  * Kelp must mirror onto kelp.
A hypothesis is eliminated on the first contradiction. If all three die we
set `contradiction` and stop predicting from symmetry for the whole match.
"""

from geometry import EDGE_KELP

HYPOTHESES = ("V", "H", "R")


class SymmetryTracker:
    __slots__ = ("alive", "contradiction")

    def __init__(self):
        self.alive = {"V": True, "H": True, "R": True}
        self.contradiction = False

    def locked(self):
        if self.contradiction:
            return None
        live = [h for h in HYPOTHESES if self.alive[h]]
        return live[0] if len(live) == 1 else None

    def eliminate(self, hyp):
        self.alive[hyp] = False
        if not any(self.alive.values()):
            # Fail safe: never predict from symmetry again, never raise.
            self.contradiction = True

    def accept_report(self, hyp):
        """A teammate says the symmetry is `hyp`. Trust it unless our own
        evidence already ruled it out."""
        if self.contradiction or not self.alive.get(hyp, False):
            return
        for h in HYPOTHESES:
            self.alive[h] = (h == hyp)

    def observe(self, snap, mem):
        """Test every live hypothesis against this turn's observations.

        Must run after mem has stored this turn's countdowns.
        """
        if self.contradiction or self.locked() is not None:
            return
        geo = mem.geo
        now = snap.round
        cd_val, cd_round, cd_src = mem.cd_val, mem.cd_round, mem.cd_src
        seen_round = mem.seen_round
        special = geo.special
        for hyp in HYPOTHESES:
            if not self.alive[hyp]:
                continue
            ok = True
            for i, c in snap.countdowns.items():
                m = geo.mirror(i, hyp)
                if m == i:
                    continue
                v = cd_val[m]
                if v is None or cd_src[m] != 1:
                    continue
                if (c < 0) != (v < 0):
                    ok = False
                    break
                if c < 0:
                    continue
                rem = v - (now - cd_round[m])
                if rem >= 1 and rem != c:
                    ok = False
                    break
            if ok:
                # kelp must mirror onto kelp (only where the mirror edge is known)
                for i in snap.visible:
                    for d in (0, 1, 2, 3):
                        sp = special.get(geo.edge_key(i, d))
                        if sp is None or sp[0] != EDGE_KELP:
                            continue
                        m = geo.mirror(i, hyp)
                        md = geo.mirror_dir(d, hyp)
                        across = geo.plain(m, md)
                        if seen_round[m] < 0 and seen_round[across] < 0:
                            continue   # mirror edge never observed
                        msp = special.get(geo.edge_key(m, md))
                        if msp is None or msp[0] != EDGE_KELP:
                            ok = False
                            break
                    if not ok:
                        break
            if not ok:
                self.eliminate(hyp)
                if self.contradiction:
                    return

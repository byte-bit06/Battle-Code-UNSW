"""The high-level policy: which option to run THIS turn (decided every turn).

Both managers return a RANKING of the feasible options, so the Brain can fall
back to the next choice if the first one has nothing to do this turn.

LearnedManager   the AI: a small MLP scoring every option (Q-values), trained
                 by hrl_train/train_manager.py and shipped as plain lists in
                 manager_weights.py. Pure Python: the judge's sandbox has no
                 torch, and ~2,300 multiply-adds is cheap next to one BFS.
ScriptedManager  plain if/else rules: the teacher the AI first imitates, and
                 the baseline it has to beat. Never shipped as the decider.
"""

import config
import features
from options import IDX, N_OPTIONS

F, EX, RA, ES, DS = (IDX["FORAGE"], IDX["EXPLORE"], IDX["RAM_TRADE"], IDX["ESCAPE"],
                     IDX["DEFENSIVE_SPLIT"])

# feature indices used by the scripted rules (see features.BASE_NAMES)
_N_LEGAL = features.BASE_NAMES.index("n_legal")
_DANGER = features.BASE_NAMES.index("danger")


class ScriptedManager:
    """The pre-HRL bot, decomposed: Instinct (ESCAPE) whenever an enemy head is
    within INSTINCT_DANGER_DIST, otherwise the Forage engine, otherwise explore.
    It never picks the new options."""
    name = "scripted"

    def rank(self, feats, mask):
        order = []
        if feats[_N_LEGAL] == 0:
            order.append(RA)                      # doomed: take one with us
        order.append(DS)
        if feats[_DANGER]:
            order.append(ES)
        order += [F, EX]
        seen = set()
        out = []
        for i in order:
            if mask[i] and i not in seen:
                seen.add(i)
                out.append(i)
        return out


class LearnedManager:
    name = "learned"

    def __init__(self, weights=None):
        if weights is None:
            import manager_weights as weights
        n_in = features.size(N_OPTIONS)
        if len(weights.MEAN) != n_in or len(weights.W2) != N_OPTIONS:
            # weights from another feature/option layout would be read silently
            # wrong (zip truncates): refuse them, make() falls back
            raise ValueError("manager weights do not match this bot's features/options")
        self.mean = weights.MEAN
        self.std = weights.STD
        self.w1 = weights.W1          # hidden x inputs
        self.b1 = weights.B1
        self.w2 = weights.W2          # options x hidden
        self.b2 = weights.B2

    def q_values(self, feats):
        x = [(v - m) / s for v, m, s in zip(feats, self.mean, self.std)]
        h = []
        for row, b in zip(self.w1, self.b1):
            a = b
            for w, v in zip(row, x):
                a += w * v
            h.append(a if a > 0.0 else 0.0)
        q = []
        for row, b in zip(self.w2, self.b2):
            a = b
            for w, v in zip(row, h):
                a += w * v
            q.append(a)
        return q

    def rank(self, feats, mask):
        q = self.q_values(feats)
        valid = [i for i in range(len(mask)) if mask[i]]
        valid.sort(key=lambda i: -q[i])
        return valid


def make(kind=None):
    kind = config.HRL_MANAGER if kind is None else kind
    if kind == "learned":
        try:
            return LearnedManager()
        except Exception:
            return ScriptedManager()     # no usable weights: never ship a dead bot
    return ScriptedManager()


def explore_rank(ranked, mask, epsilon, rng=None):
    """Training only: with probability epsilon, a random valid option goes first."""
    if epsilon <= 0:
        return ranked
    if rng is None:
        import random as rng     # not imported by the shipped bot: imports cost points
    if rng.random() >= epsilon:
        return ranked
    valid = [i for i in range(len(mask)) if mask[i]]
    if not valid:
        return ranked
    pick = rng.choice(valid)
    return [pick] + [i for i in ranked if i != pick]

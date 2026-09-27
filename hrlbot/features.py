"""The manager's observation: a short vector of situation facts, not raw tiles.

Built mostly from options.Facts (no extra search), so the manager sees what
the options see. Layout:
    BASE_NAMES           situation facts (below)
    + N_OPTIONS          feasibility mask: which options could act this turn
    + N_OPTIONS          one-hot of the option this dragon ran LAST turn
                         (so the AI can learn to commit to a plan, or not)

The ORDER is part of the trained model: append new features at the end of
BASE_NAMES and retrain; never reorder.
"""

import config

BASE_NAMES = [
    "length", "units", "round", "is_longest", "n_legal", "danger", "rammable",
    "n_enemies", "enemy_dist", "enemy_len_ratio", "enemy_fully_seen",
    "n_allies", "ally_dist", "longest_ally_ratio", "can_feed_now", "best_len_heard_ratio",
    "pearls_near", "nearest_pearl", "cluster", "reports_near", "predicted_soon",
    "portal_near", "explored", "symmetry_locked", "can_split_half", "can_ram_now",
]


def build(t, mask, prev):
    f = t.facts()
    snap, mem = t.snap, t.mem
    L = snap.my_len
    ne = f.nearest_enemy
    na = f.allies[0] if f.allies else None
    longest_ally = max((h.visible_len for _m, h in f.allies), default=0)
    out = [
        min(L / 20.0, 3.0),
        min(t.unit_count / 16.0, 2.0),
        snap.round / 500.0,
        1.0 if mem.is_longest(snap) else 0.0,
        len(t.legal) / 4.0,
        1.0 if t.danger() else 0.0,
        1.0 if t.rammable() else 0.0,
        min(len(f.enemies) / 3.0, 2.0),
        min(ne[0] / 12.0, 1.0) if ne else 1.0,
        min(ne[1].visible_len / L, 3.0) if ne else 0.0,
        1.0 if ne and ne[1].pos in snap.release else 0.0,
        min(len(f.allies) / 3.0, 2.0),
        min(na[0] / 12.0, 1.0) if na else 1.0,
        min(longest_ally / L, 3.0),
        1.0 if f.feed_dir is not None else 0.0,
        min(mem.best_len_heard / L, 3.0),
        min(f.pearls_near / 8.0, 3.0),
        min(f.nearest_pearl / 14.0, 1.0),
        min(f.cluster / 6.0, 2.0),
        min(f.reports_near / 3.0, 1.0),
        min(f.predicted_soon / 8.0, 3.0),
        (1.0 - f.portal / config.PORTAL_RADIUS) if f.portal is not None else 0.0,
        f.explored,
        1.0 if mem.sym.locked() is not None else 0.0,
        1.0 if t.ct.can_split(L // 2) else 0.0,
        1.0 if f.ram_dir is not None else 0.0,
    ]
    out.extend(1.0 if m else 0.0 for m in mask)
    out.extend(1.0 if i == prev else 0.0 for i in range(len(mask)))
    return out


def size(n_options):
    return len(BASE_NAMES) + 2 * n_options

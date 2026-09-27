"""Phase 2 tests for the HRL bot (hrlbot/).

    python -m pytest -q hrl_tests
"""
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "hrl_train"))

import botenv       # noqa: E402
import scenarios    # noqa: E402

import pytest       # noqa: E402

HRL = botenv.BotSpec.load("hrlbot")
O = HRL.mods["options"]
F = HRL.mods["features"]
M = HRL.mods["manager"]


@pytest.fixture(autouse=True)
def _isolate_bot_modules():
    """hrlbot's modules share names with mybot's (the instinct_tests import
    mybot's): never leave ours installed after a test."""
    with botenv.restored():
        yield


def turn_for(sim, dragon, first=False):
    """A real options.Turn for `dragon`, built through the bot's own snapshot."""
    HRL.activate()
    HRL.helper.game = game = botenv.FakeGame(sim)
    ct = botenv.FakeController(sim, dragon, HRL.helper)
    brain = HRL.main.Brain(sim.W, sim.H)
    snap = HRL.mods["snapshot"].build(ct, game, brain.mem.geo, HRL.main.DIR_INDEX)
    brain.mem.update(snap)
    return O.Turn(ct, snap, brain.mem, HRL.main.Deadline(10.0), first)


def board(builder, seed=0):
    import sim as simmod
    sc = builder(seed, random.Random(seed))
    s = simmod.Sim(sc["map"], seed=seed)
    if sc.get("setup"):
        sc["setup"](s)
    return s


def ours(s):
    return next(d for d in s.dragons.values() if d.team == "A")


# ---------------------------------------------------------------- shape --
def test_option_list_is_the_action_space():
    assert O.NAMES == ["FORAGE", "CAMP_CLUSTER", "SCAVENGE", "EXPLORE", "PORTAL_TRAVEL", "HUNT",
                       "SPLIT_AND_PINCER", "RAM_TRADE", "ESCAPE", "DEFENSIVE_SPLIT", "ECON_SPLIT",
                       "STALL"]
    for o in O.make_options():
        assert hasattr(o, "can_start") and hasattr(o, "step") and hasattr(o, "should_stop")


def test_features_have_a_fixed_size():
    s = board(scenarios.s_forage)
    t = turn_for(s, ours(s))
    mask = [True] * O.N_OPTIONS
    assert len(F.build(t, mask)) == F.size(O.N_OPTIONS)


def test_scripted_manager_only_ranks_available_options():
    mask = [False] * O.N_OPTIONS
    mask[O.IDX["EXPLORE"]] = True
    feats = [0.5] * F.size(O.N_OPTIONS)
    assert M.ScriptedManager().rank(feats, mask) == [O.IDX["EXPLORE"]]


def test_learned_manager_is_the_numpy_mlp():
    np = __import__("numpy")
    rng = np.random.default_rng(0)
    n_in, n_h, n_out = F.size(O.N_OPTIONS), 7, O.N_OPTIONS

    class W:
        MEAN = rng.normal(size=n_in).tolist()
        STD = (rng.random(n_in) + 0.5).tolist()
        W1 = rng.normal(size=(n_h, n_in)).tolist()
        B1 = rng.normal(size=n_h).tolist()
        W2 = rng.normal(size=(n_out, n_h)).tolist()
        B2 = rng.normal(size=n_out).tolist()
    x = rng.normal(size=n_in)
    q = M.LearnedManager(W).q_values(x.tolist())
    h = np.maximum(0, np.array(W.W1) @ ((x - W.MEAN) / W.STD) + W.B1)
    expect = np.array(W.W2) @ h + W.B2
    assert np.allclose(q, expect)
    mask = [i % 2 == 0 for i in range(n_out)]
    ranked = M.LearnedManager(W).rank(x.tolist(), mask)
    assert all(mask[i] for i in ranked) and ranked[0] == max(
        (i for i in range(n_out) if mask[i]), key=lambda i: expect[i])


# --------------------------------------------------------------- shield --
def test_shield_blocks_kelp_bodies_and_bad_splits():
    s = board(scenarios.s_defensive_split)          # coiled in a sealed room
    me = ours(s)
    t = turn_for(s, me)
    for d in range(4):
        out = O.shield(t, ("move", [d]))
        if d in t.legal:
            assert out is not None
        else:
            assert out is None                      # kelp or our own body
    assert O.shield(t, ("split", 1)) is None        # child must be >= 2
    assert O.shield(t, ("split", me.length - 1)) is None
    assert O.shield(t, ("split", 3)) == ("split", 3)


def test_shield_blocks_unaffordable_sprints():
    s = board(scenarios.s_forage)                   # we are length 3
    t = turn_for(s, ours(s))
    d = t.legal[0]
    assert O.shield(t, ("move", [d, d, d])) is None  # 3 steps would need length > 3


def test_shield_allows_a_deliberate_trade_onto_an_enemy_head():
    s = board(scenarios.s_ram)
    enemy = next(d for d in s.dragons.values() if d.team == "B")
    s.apply(enemy, ("move", [3]))                   # enemy steps next to our head
    t = turn_for(s, ours(s))
    assert t.facts().ram_dir is not None
    d = t.facts().ram_dir[0]
    assert d not in t.legal                         # safety.py calls it a body...
    assert O.shield(t, ("move", [d])) == ("move", [d])   # ...the shield lets RAM through


# ---------------------------------------------------- initiation sets --
def test_initiation_sets_match_their_boards():
    s = board(scenarios.s_ram)
    enemy = next(d for d in s.dragons.values() if d.team == "B")
    s.apply(enemy, ("move", [3]))
    t = turn_for(s, ours(s))
    assert O.RamTrade().can_start(t)                # we are 3, they are 12
    assert not O.EconSplit().can_start(t)           # too short, enemy close
    s = board(scenarios.s_econ)
    t = turn_for(s, ours(s))
    assert O.EconSplit().can_start(t)               # long, alone
    assert not O.RamTrade().can_start(t)
    s = board(scenarios.s_scavenge)
    t = turn_for(s, ours(s))
    assert O.Scavenge().can_start(t)                # a corpse in view
    assert O.Explore().can_start(t)                 # always


# --------------------------------------------------------- whole games --
def test_random_option_choices_never_cause_an_illegal_action():
    """epsilon = 1: the manager picks a random available option every time.
    Whatever the options do, the shield must never let an illegal split, an
    over-sprint or a no-action through."""
    me = botenv.BotSpec.load("hrlbot")
    me.config.INSTINCT_RAISE = False

    def on_brain(brain, d):
        brain.epsilon = 1.0
        brain.rng = random.Random(d.id)
    for m in ("arena", "Colosseum"):
        r = botenv.play_game(os.path.join(ROOT, "maps", m + ".map"), 3, me,
                             botenv.BotSpec.load("mybot"), max_rounds=120, record=("A",),
                             on_brain=on_brain)
        bad = [lg.death_cause for lg in r["logs"].values() if lg.team == "A" and
               lg.death_cause in ("illegal split", "over-sprinted", "no valid action")]
        assert not bad, bad
        picked = {d["option"] for lg in r["logs"].values() for d in lg.decisions}
        assert len(picked) >= 4                      # random choices really happened


def test_option_scenarios_smoke():
    assert scenarios.run("RAM_TRADE", 0)[0]          # the trade happens
    assert scenarios.run("PORTAL_TRAVEL", 0)[0]      # it goes through the portal

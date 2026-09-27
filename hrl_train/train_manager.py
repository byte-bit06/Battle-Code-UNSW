"""Phase 5: train the manager (which option to run) on frozen options.

    python hrl_train/train_manager.py --iters 30

Pipeline
  1. demonstrations  games with the scripted manager (plus some random-option
                     games for coverage), recorded per decision
  2. pretrain        behaviour cloning, DQfD-style: TD loss on every transition
                     plus a large-margin loss that makes the scripted choice the
                     argmax, so the net starts as the baseline with meaningful Q
  3. self-play RL    Double DQN over OPTIONS (an SMDP): a decision's reward is
                     everything that happened until the next decision and the
                     bootstrap is discounted by gamma ** (turns the option ran).
                     Opponents: mybot, the scripted HRL bot, and past snapshots.
                     Maps, seeds and team side are random every game.
  4. export          the best snapshot (by evaluation vs mybot) becomes
                     hrlbot/manager_weights.py, plain lists for the judge.

Reward per decision (one dragon, from this decision to the next):
    length gained  + length handed to split children (splits are not a loss)
  + KILL_R + 0.25 * victim length for each enemy that died on us
  - DEATH_R - 0.5 * our length if we died
  +/- WIN_R at the end of the game for dragons still alive
"""
import argparse
import glob
import json
import os
import random
import sys
import time
import types
from concurrent.futures import ProcessPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

GAMMA = 0.98
KILL_R, DEATH_R, WIN_R = 3.0, 5.0, 10.0
# credit a split with its child's lifetime growth (--child-credit); read from the
# environment so the spawned rollout workers see the value the main process set
CHILD_W = float(os.environ.get("HRL_CHILD_W", "0"))
HIDDEN = 32
MARGIN = 0.8


# ============================================================ rollouts ==
def weights_ns(w):
    return None if w is None else types.SimpleNamespace(**w)


def child_gain(r, cid, k):
    """Length a split child added over its life (0 if it never grew)."""
    lg = r["logs"].get(cid)
    if lg is None:
        return 0.0
    end_len = lg.death_len if lg.death_round is not None else r["sim"].dragons[cid].length
    return max(0.0, end_len - k)


def transitions(r, side):
    """Per-dragon decisions -> SMDP transitions (numpy arrays)."""
    S, A, R, T, S2, M2, D, M = [], [], [], [], [], [], [], []
    sim = r["sim"]
    win = 1 if r["winner"] == side else (-1 if r["winner"] not in (None, side) else 0)
    for lg in r["logs"].values():
        if lg.team != side or not lg.decisions:
            continue
        ds = lg.decisions
        for i, d in enumerate(ds):
            start, L0 = d["round"], d["length"]
            extra = 0.0
            if i + 1 < len(ds):
                nxt = ds[i + 1]
                end, L1, done = nxt["round"], nxt["length"], False
                s2, m2 = nxt["feats"], nxt["mask"]
            else:
                done, s2, m2 = True, d["feats"], d["mask"]
                if lg.death_round is not None:
                    end, L1 = lg.death_round + 1, lg.death_len
                    extra = -(DEATH_R + 0.5 * lg.death_len)
                else:
                    end, L1 = r["rounds"], sim.dragons[lg.id].length
                    extra = WIN_R * win
            rew = (L1 - L0) + extra
            for rd, k, *child in lg.split_credit:
                if start <= rd < end:
                    rew += k                           # the length handed over is not lost
                    if CHILD_W and child:              # ...and the child's growth is ours
                        rew += CHILD_W * child_gain(r, child[0], k)
            rew += sum(KILL_R + 0.25 * l for rd, l in lg.kills if start <= rd < end)
            S.append(d["feats"])
            M.append(d["mask"])
            A.append(d["option"])
            R.append(rew)
            T.append(max(1, end - start))
            S2.append(s2)
            M2.append(m2)
            D.append(done)
    if not S:
        return None
    f32 = lambda x: np.asarray(x, dtype=np.float32)
    return {"s": f32(S), "m": np.asarray(M, bool), "a": np.asarray(A, np.int64), "r": f32(R),
            "t": f32(T), "s2": f32(S2), "m2": np.asarray(M2, bool), "d": f32(D)}


def rollout(job):
    """One game. job: dict(map, seed, side, weights, epsilon, opponent, opp_weights)"""
    import botenv
    me = botenv.BotSpec.load("hrlbot")
    mgr = me.mods["manager"]
    w = weights_ns(job["weights"])
    make_me = (lambda: mgr.LearnedManager(w)) if w is not None else (lambda: mgr.ScriptedManager())
    eps = job["epsilon"]

    def on_brain(brain, d):
        brain.epsilon = eps
        brain.rng = random.Random(job["seed"] * 1000 + d.id)
    me.brain_factory = lambda sp, s, d: sp.main.Brain(s.W, s.H, make_me())
    opp = job["opponent"]
    if opp == "mybot":
        other = botenv.BotSpec.load("mybot")
    else:
        other = botenv.BotSpec.load("hrlbot")
        ow = weights_ns(job.get("opp_weights"))
        other.brain_factory = (lambda sp, s, d: sp.main.Brain(s.W, s.H, mgr.LearnedManager(ow))) \
            if ow is not None else (lambda sp, s, d: sp.main.Brain(s.W, s.H, mgr.ScriptedManager()))
    side = job["side"]
    a, b = (me, other) if side == "A" else (other, me)
    r = botenv.play_game(job["map"], job["seed"], a, b, record=(side,), on_brain=on_brain)
    tr = transitions(r, side)
    outcome = "WIN" if r["winner"] == side else ("DRAW" if r["winner"] is None else "LOSS")
    return tr, outcome, os.path.basename(job["map"])[:-4]


def collect(pool, n_games, weights, epsilon, rng, opponents, past=(), demo=False):
    maps = sorted(glob.glob(os.path.join(ROOT, "maps", "*.map")))
    jobs = []
    for _ in range(n_games):
        opp = rng.choice(opponents)
        ow = None
        if opp == "past":
            if past:
                ow = rng.choice(past)
                opp = "hrl"
            else:
                opp = "mybot"
        jobs.append({"map": rng.choice(maps), "seed": rng.randrange(10 ** 6), "side": rng.choice("AB"),
                     "weights": weights, "epsilon": epsilon, "opponent": opp, "opp_weights": ow})
    out, outcomes = [], []
    for tr, outcome, _m in pool.map(rollout, jobs):
        outcomes.append(outcome)
        if tr is not None:
            tr["demo"] = np.full(len(tr["a"]), demo, bool)
            out.append(tr)
    return out, outcomes


def merge(chunks):
    return {k: np.concatenate([c[k] for c in chunks]) for k in chunks[0]}


# ============================================================= learner ==
class Learner:
    def __init__(self, n_in, n_out, mean, std, seed=0):
        import torch
        self.torch = torch
        torch.manual_seed(seed)
        nn = torch.nn
        self.mean = torch.tensor(mean, dtype=torch.float32)
        self.std = torch.tensor(std, dtype=torch.float32)
        mk = lambda: nn.Sequential(nn.Linear(n_in, HIDDEN), nn.ReLU(), nn.Linear(HIDDEN, n_out))
        self.q = mk()
        self.q_target = mk()
        self.q_target.load_state_dict(self.q.state_dict())
        self.opt = torch.optim.Adam(self.q.parameters(), lr=1e-3)

    def _x(self, s):
        return (s - self.mean) / self.std

    def train(self, buf, steps, batch=512, margin_w=1.0, target_every=250):
        torch = self.torch
        n = len(buf["a"])
        tb = {k: torch.as_tensor(v) for k, v in buf.items()}
        demo_idx = np.flatnonzero(buf["demo"])
        losses = []
        for step in range(steps):
            idx = torch.as_tensor(np.random.randint(0, n, batch))
            s, a, r, t = tb["s"][idx], tb["a"][idx], tb["r"][idx], tb["t"][idx]
            s2, m2, d = tb["s2"][idx], tb["m2"][idx], tb["d"][idx]
            q = self.q(self._x(s))
            q_sa = q.gather(1, a[:, None]).squeeze(1)
            with torch.no_grad():
                q2_online = self.q(self._x(s2)).masked_fill(~m2, -1e9)
                a2 = q2_online.argmax(1, keepdim=True)
                q2 = self.q_target(self._x(s2)).gather(1, a2).squeeze(1)
                y = r + (GAMMA ** t) * (1 - d) * q2
            loss = torch.nn.functional.smooth_l1_loss(q_sa, y)
            if margin_w > 0 and len(demo_idx):
                j = torch.as_tensor(np.random.choice(demo_idx, min(batch, len(demo_idx))))
                qs = self.q(self._x(tb["s"][j]))
                ae = tb["a"][j]
                marg = torch.full_like(qs, MARGIN)
                marg.scatter_(1, ae[:, None], 0.0)
                qm = (qs + marg).masked_fill(~tb["m"][j], -1e9)
                loss = loss + margin_w * (qm.max(1).values - qs.gather(1, ae[:, None]).squeeze(1)).mean()
            self.opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.q.parameters(), 10.0)
            self.opt.step()
            losses.append(float(loss))
            if (step + 1) % target_every == 0:
                self.q_target.load_state_dict(self.q.state_dict())
        return float(np.mean(losses[-200:]))

    def agreement(self, buf):
        """How often argmax Q (masked) equals the recorded action on demo data."""
        torch = self.torch
        sel = np.flatnonzero(buf["demo"])[:20000]
        if not len(sel):
            return float("nan")
        with torch.no_grad():
            q = self.q(self._x(torch.as_tensor(buf["s"][sel]))).masked_fill(
                ~torch.as_tensor(buf["m"][sel]), -1e9)
        return float((q.argmax(1).numpy() == buf["a"][sel]).mean())

    def export(self):
        sd = self.q.state_dict()
        return {"MEAN": self.mean.tolist(), "STD": self.std.tolist(),
                "W1": sd["0.weight"].tolist(), "B1": sd["0.bias"].tolist(),
                "W2": sd["2.weight"].tolist(), "B2": sd["2.bias"].tolist()}


def write_weights(w, path, note):
    rnd = lambda x: [round(v, 5) for v in x]
    with open(path, "w") as f:
        f.write(f'"""Trained manager weights (generated by hrl_train/train_manager.py).\n\n{note}\n"""\n')
        f.write(f"MEAN = {rnd(w['MEAN'])}\n")
        f.write(f"STD = {rnd(w['STD'])}\n")
        f.write("W1 = [\n" + "".join(f"    {rnd(r)},\n" for r in w["W1"]) + "]\n")
        f.write(f"B1 = {rnd(w['B1'])}\n")
        f.write("W2 = [\n" + "".join(f"    {rnd(r)},\n" for r in w["W2"]) + "]\n")
        f.write(f"B2 = {rnd(w['B2'])}\n")


# ================================================================= main ==
def quick_eval(pool, weights, rng, n_games):
    maps = sorted(glob.glob(os.path.join(ROOT, "maps", "*.map")))
    jobs = [{"map": m, "seed": 5000 + s, "side": side, "weights": weights, "epsilon": 0.0,
             "opponent": "mybot", "opp_weights": None}
            for s in range(max(1, n_games // (2 * len(maps)))) for m in maps for side in "AB"]
    outs = [o for _tr, o, _m in pool.map(rollout, jobs)]
    return sum(o == "WIN" for o in outs) / len(outs), len(outs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=30)
    ap.add_argument("--demo-games", type=int, default=96)
    ap.add_argument("--games", type=int, default=32, help="self-play games per iteration")
    ap.add_argument("--steps", type=int, default=1500)
    ap.add_argument("--pretrain-steps", type=int, default=4000)
    ap.add_argument("--eval-every", type=int, default=5)
    ap.add_argument("--eval-games", type=int, default=32)
    ap.add_argument("--buffer", type=int, default=400_000)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--out", default=os.path.join(HERE, "runs", time.strftime("%Y%m%d-%H%M")))
    ap.add_argument("--child-credit", type=float, default=0.0,
                    help="reward a split with this x its child's lifetime growth")
    args = ap.parse_args()
    global CHILD_W
    CHILD_W = args.child_credit
    os.environ["HRL_CHILD_W"] = str(CHILD_W)       # workers are separate processes
    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(1)
    logf = open(os.path.join(args.out, "log.txt"), "a")

    def log(msg):
        print(msg, flush=True)
        logf.write(msg + "\n")
        logf.flush()

    log(f"=== train_manager {time.strftime('%Y-%m-%d %H:%M')} {vars(args)}")
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        t0 = time.time()
        demo, outs = collect(pool, args.demo_games, None, 0.0, rng, ["mybot", "hrl"], demo=True)
        cover, outs2 = collect(pool, args.demo_games // 3, None, 0.3, rng, ["mybot", "hrl"])
        buf = merge(demo + cover)
        log(f"demonstrations: {len(buf['a'])} decisions from {len(outs) + len(outs2)} games "
            f"({time.time() - t0:.0f}s); scripted win rate in them "
            f"{sum(o == 'WIN' for o in outs) / len(outs):.0%}")
        mean = buf["s"].mean(0)
        std = buf["s"].std(0) + 1e-3
        L = Learner(buf["s"].shape[1], buf["m"].shape[1], mean, std)
        loss = L.train(buf, args.pretrain_steps, margin_w=1.0)
        log(f"pretrain: loss {loss:.3f}, agrees with the scripted manager on "
            f"{L.agreement(buf):.1%} of its decisions")
        w = L.export()
        wr, n = quick_eval(pool, w, rng, args.eval_games)
        log(f"iter 0 (behaviour cloned): win rate vs mybot {wr:.0%} (n={n})")
        best = (wr, 0, w)
        past = [w]
        json.dump(w, open(os.path.join(args.out, "w_0.json"), "w"))
        for it in range(1, args.iters + 1):
            eps = max(0.05, 0.3 * (1 - it / (0.7 * args.iters)))
            t1 = time.time()
            chunks, outs = collect(pool, args.games, w, eps, rng, ["mybot", "mybot", "hrl", "past"],
                                   past=past)
            buf = merge([buf] + chunks)
            if len(buf["a"]) > args.buffer:          # keep demos, drop the oldest self-play
                keep = np.concatenate([np.flatnonzero(buf["demo"]),
                                       np.flatnonzero(~buf["demo"])[-(args.buffer // 2):]])
                buf = {k: v[keep] for k, v in buf.items()}
            margin_w = max(0.05, 1.0 * (1 - it / (0.5 * args.iters)))
            loss = L.train(buf, args.steps, margin_w=margin_w)
            w = L.export()
            past.append(w)
            past = past[-6:]
            json.dump(w, open(os.path.join(args.out, f"w_{it}.json"), "w"))
            line = (f"iter {it}: eps {eps:.2f} margin {margin_w:.2f} loss {loss:.3f} "
                    f"buffer {len(buf['a'])} self-play W/L {sum(o == 'WIN' for o in outs)}/"
                    f"{sum(o == 'LOSS' for o in outs)} agree {L.agreement(buf):.0%} "
                    f"({time.time() - t1:.0f}s)")
            if it % args.eval_every == 0 or it == args.iters:
                wr, n = quick_eval(pool, w, rng, args.eval_games)
                line += f" | eval vs mybot {wr:.0%} (n={n})"
                if wr > best[0]:
                    best = (wr, it, w)
            log(line)
        log(f"best: iter {best[1]} with {best[0]:.0%} vs mybot")
        json.dump(best[2], open(os.path.join(args.out, "best.json"), "w"))
        write_weights(best[2], os.path.join(args.out, "manager_weights.py"),
                      f"Run {os.path.basename(args.out)}, iteration {best[1]}, "
                      f"quick-eval win rate vs mybot {best[0]:.0%}.")
        log(f"wrote {os.path.join(args.out, 'manager_weights.py')}")


if __name__ == "__main__":
    main()

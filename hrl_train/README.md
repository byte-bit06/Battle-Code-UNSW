# HRL training tools

Everything here trains or measures `hrlbot/` (the Hierarchical RL bot) on the
Python simulator in `arena/sim.py`. The design and the results are in
`HRL_CHECKLIST.md` at the repo root.

All commands run from the repo root. They use every core but two by default
(`--workers N` to change that).

| Step | Command | What it does |
|---|---|---|
| Unit tests | `python -m pytest -q hrl_tests` | options, shield, features, manager maths, a random-option fuzz game |
| Option scenarios | `python hrl_train/scenarios.py [OPTION ...] --seeds 8` | one small board per option: forced option vs the scripted manager |
| Tune options | `python hrl_train/tune_options.py HUNT ECON_SPLIT` | CEM over an option's parameters on full games (Phase 4) |
| Train manager | `python hrl_train/train_manager.py --iters 30` | behaviour cloning, then Double DQN over options with self-play (Phase 5) |
| Evaluate | `python hrl_train/evaluate.py hrlbot mybot --seeds 3` | every map, both sides; win rate plus option usage stats (Phase 7) |
| Real engine | `unswbc run maps/default.map hrlbot mybot` | the official engine (what the ladder runs) |
| Judge CPU | `unswbc run --sandbox -v --no-replay maps/default_small.map hrlbot mybot > run.txt 2>&1` then `python forage_tests/sandbox_points.py run.txt` | CPU points per turn (limit 100M) |

## Files

- `botenv.py`: plays any two bot folders against each other in one process.
  Every bot uses the same module names, so each bot's modules are loaded
  once and swapped into `sys.modules` before each of its dragons moves (and
  swapped back out afterwards). The engine side of the helper API is
  `arena/fake.py`, which is shared with the local arena viewer.
- `evaluate.py`: parallel evaluation, option usage stats (`--manager`,
  `--weights`, `--set NAME=VALUE`).
- `scenarios.py`: the per-option test boards and scripted opponents.
- `tune_options.py`: Phase 4 (log in `results/tuning.txt`).
- `train_manager.py`: Phase 5. Each run writes `runs/<name>/`: `log.txt`,
  `best.json` and `manager_weights.py` for the best iteration, plus
  per-iteration `w_N.json` snapshots, which git ignores. `runs/main/` is the
  run that produced the shipped `hrlbot/manager_weights.py`.
- `results/`: saved outputs quoted in `HRL_CHECKLIST.md`:
  - `baseline_scripted.*`: Phase 3
  - `scenarios_v1.txt`: Phase 1/2 option scenarios
  - `tuning.txt`: Phase 4
  - `final_learned.*`: Phase 7
  - `sandbox_cpu.txt`: judge CPU points

## What else is in the repo

| Folder | What it is | Used by the HRL bot? |
|---|---|---|
| `hrlbot/` | the HRL bot (self-contained: it is what gets submitted) | it *is* the bot |
| `mybot/` | the Instinct_Engine bot | the baseline opponent in every evaluation |
| `arena/` | the rules simulator (`sim.py`), map parser, shared fake controller, human-vs-bot viewer | training and evaluation run on it |
| `forage_tests/`, `instinct_tests/` | tests for the engines `hrlbot` copies | indirectly (they test the same code) |
| `tools/` | Instinct analysis, and `evaluate.py` for **real-engine** matches (`hrl_train/evaluate.py` is the simulator version) | no |
| `humanbot/`, `probe_bot/` | play by hand in the real engine; the probe that verified the simulator against the engine | no |

`hrlbot/` repeats most of `mybot/`'s modules on purpose: every bot folder is
submitted on its own, so it can't import from another folder. `hrlbot`'s
copies are trimmed to what it calls, and its `forage.py` has extra `kinds` and
`fallback` parameters.

## Shipping a new manager

1. Train: `python hrl_train/train_manager.py`.
2. Check it: `python hrl_train/evaluate.py hrlbot mybot --weights hrl_train/runs/<run>/manager_weights.py --seeds 3`.
3. Copy `runs/<run>/manager_weights.py` over `hrlbot/manager_weights.py`.
4. Re-run the judge CPU check before submitting.

If `hrlbot/manager_weights.py` is missing or broken, the bot falls back to
the scripted manager on its own, so it never ships a dead bot.

## Changing the options or features

The option ORDER (`options.make_options`) and the feature ORDER
(`features.BASE_NAMES`) are the network's inputs and outputs. Add to the end
and retrain; never reorder or delete without retraining.

# HRL Bot — Build Checklist

Goal: a new bot that uses **Hierarchical Reinforcement Learning (HRL)**. A small
learned **manager** looks at the situation and picks an **abstract action**
("option"): *"enemy head nearby and we're longer, split and kill"*, *"pearl
cluster here, curl up and camp it"*. The option's own policy then plays the
individual moves until the option finishes or gets interrupted.

We are **not** starting from scratch. Most options already exist as hand-written
code on the engine branches (mainly `Instinct_Engine`, which contains Forage +
Defence + Instinct). We wrap that code as options, train only where it's weak,
and let the manager learn *when* to use each one.

The bot is in `hrlbot/`, and the training/measurement tools are in `hrl_train/`
(see `hrl_train/README.md`). The tests are in `hrl_tests/`. All of it lives on
the local branch `HRL_Engine`, made from `origin/Instinct_Engine`.

---

## Status (2026-09-27)

**Latest change: full AI autonomy (code only, NOT trained yet).**
- The AI (manager) now picks an option **every turn**, and each option only
  supplies that turn's move.
- The options' start rules are **feasibility only** ("is this move physically
  possible now?"). All timing and length rules were removed so the AI decides
  them: when to split, hunt, stall, ram, and when to feed which teammate.
- Two new options, **FEED_LONGEST** and **FEED_NEAREST**, sacrifice this
  dragon into a teammate's body so the teammate can eat the dropped pearls.
  The shield allows exactly that one deliberate death, plus the RAM_TRADE trade.
- The AI's inputs now include teammate facts, "can an enemy ram us this
  turn", and which option it ran last turn: 26 facts + 14 feasibility flags +
  14 last-option flags = 54 inputs.
- Rewards credit a split with its child's growth and a sacrifice with the
  teammate's growth. Every dragon, dead or alive, gets the team's final result,
  discounted by how long before the end it stopped.
- Checked: the scripted teacher is at parity under the new loop (**50%** vs
  `mybot`, 48 games); judge CPU typical 41M / worst 77M of 100M, no CPU
  deaths; 127 tests pass.
- **There are no trained weights for this layout yet.** The old ones don't fit
  the new inputs, so the bot runs the scripted manager until someone trains it:
  `python hrl_train/train_manager.py --iters 30 --eval-games 48`.

The results table below is from the previous design (12 options, decisions
every 4 turns).

**Results so far (simulator, vs `mybot` = the `Instinct_Engine` bot):**

| Bot | Win rate | Games |
|---|---|---|
| `mybot` vs itself (what "even" looks like) | 48% | 48 |
| HRL, scripted manager (Phase 3 baseline) | 46% | 48 |
| HRL, learned manager (shipped in `hrlbot/manager_weights.py`) | **40%** | 48 |
| HRL, scripted manager + ECON_SPLIT forced on whenever it's available | **69–75%** | 16 per check |

**Honest reading:**
- The HRL structure works and matches the old bot. The learned manager does
  **not** beat it yet: 40% vs 46% is within the noise of 48 games.
- Self-play RL (24 iterations) didn't improve on the behaviour-cloned start,
  so the shipped weights are the cloned manager (iteration 0).
- The biggest win found is an OPTION, not the manager: splitting to farm
  (ECON_SPLIT) won 69–75% during tuning. The learned manager almost never
  picks it, probably because the reward didn't credit a split with its
  child's growth. That fix is written (`--child-credit`) but has not been run
  to completion yet.

**Not done:** Phase 6 (optional), the child-credit training run, a
multi-map check on the real engine, and `unswbc submit` (waiting for
your go-ahead).

---

## How it fits together

```
every turn:
  ┌─────────────────────────────────────────────────────────────┐
  │ 1. Build state   snapshot.py + memory.py + symmetry.py      │
  │ 2. Manager (AI)  EVERY turn: mask options that are not      │
  │                  physically possible, rank the rest         │
  │ 3. Option        option.step(state) → this turn's move /    │
  │                  sprint / split (nothing → next in the rank)│
  │ 4. Safety shield veto any move that dies (never learned)    │
  │ 5. Sonar         share what we saw with teammates           │
  └─────────────────────────────────────────────────────────────┘
```

This is the **Options framework** from the survey, trained **bottom-up**: build
and freeze the options first, then train the manager on top.

---

## Phase 0 — Set-up and constraints

- [x] Branch `HRL_Engine` from `origin/Instinct_Engine`. It is local only, with
      no upstream set, so nothing can be pushed by accident.
- [x] **What the judge allows:** Python 3.13 + **numpy only, no torch**. The
      manager therefore runs as a plain-Python MLP (weights in
      `hrlbot/manager_weights.py`). Torch is used for training only.
- [x] **CPU budget** (`unswbc run --sandbox`, default_small, learned manager):
      normal turns p50 34M / max 67M; first turns max 83M; second turns
      (which load the manager) max 67M; **0 CPU deaths** (limit 100M).
      The manager modules load on a dragon's 2nd turn because first turns
      were at 90M. Numbers: `hrl_train/results/sandbox_cpu.txt`.
- [x] Training env: `arena/sim.py` (checked against the real engine).
- [x] Headless env: `hrl_train/botenv.py`, `play_game(map, seed, botA, botB)`.
      It runs any two bot folders in one process, with no pygame, and runs in
      parallel through process pools. (It is a game-level API rather than a
      step-level Gym API, because each dragon's manager decides on its own
      schedule.)
- [x] The manager runs **per dragon**. Split children start blank; teamwork goes
      through the existing sonar protocol.

## Phase 1 — The abstract actions

| # | Option | Start when (initiation set) | Does (internal policy) | Stops when | Code | Scenario (forced vs scripted) |
|---|---|---|---|---|---|---|
| 1 | **FORAGE** | always (its own search decides) | the **whole** Forage engine: live, predicted and pile targets scored together | nothing to eat | `forage.forage_turn` | same as baseline (it *is* the baseline) |
| 2 | **CAMP_CLUSTER** | spawn tile within 8 with countdown ≤ 12 | predicted-spawn targets only; hold near the next spawn | no spawns due | `forage` predictive + hold step | 10.6 vs 14.6 length: **worse** than FORAGE |
| 3 | **SCAVENGE** | ≥ 3 pearls clustered within 6, or a teammate's death report | pile targets only (beam search), then reported piles | piles gone | `forage.beam_scavenge`, sonar reports | same as baseline |
| 4 | **EXPLORE** | always | open space + stale ground | something to eat in sight | `forage.explore` | same |
| 5 | **PORTAL_TRAVEL** | a portal edge within 10 | route to it and jump (an unknown far end is valued as a gamble) | jumped / 30 rounds | `geometry` portals | **8/8 crossed vs 0/8** |
| 6 | **HUNT** *(new)* | enemy within 6 and we're ≥ 3 longer | move to shrink its room, never rammable; chase its last sighting for 3 turns | lost for 3 turns | new, uses `instinct` | 0/8 kills vs 0/8: open boards can't be sealed (enemy room stayed 157/169 tiles) |
| 7 | **SPLIT_AND_PINCER** *(new)* | hunt target beside our rear half, length ≥ 11 | split in half, unrammable | after split | new | splits, no kills |
| 8 | **RAM_TRADE** | enemy head adjacent and `may_trade` | head-to-head | after the move | `policy.may_trade` | **8/8 vs 0/8** |
| 9 | **ESCAPE** | enemy head within 12 | Instinct's ladder; Forage when the ladder says calm | 2 calm turns | `instinct/ladder` | same as baseline (1/8 vs two cheating chasers) |
| 10 | **DEFENSIVE_SPLIT** | danger and `policy.should_split` | split | after split | `policy.should_split` | never triggered: Instinct refuses in a fully sealed room; emergency split covers it |
| 11 | **ECON_SPLIT** | length ≥ 8, no enemy within 8, < 12 teammates, round < 440 | split off a length-3 child | after split | new | team length **167 vs 72** |
| 12 | **STALL** *(new)* | round ≥ 400 or tiebreak holder, length ≥ 6 | safest move, far from enemy heads | never (manager re-decides) | new, uses `instinct` | 8/8 vs 8/8 |

- [x] List agreed. FORAGE was redefined as the whole Forage engine: splitting
      its target kinds into separate options lost 38 of 48 games, because the
      joint scoring is what makes it good. CAMP and SCAVENGE are now
      specialists.
- [x] Reward per option: see Phase 4 (`hrl_train/tune_options.py score_game`).
- [x] One scenario per option: `hrl_train/scenarios.py` (results in the table above).

## Phase 2 — Common option interface

- [x] `Option` base class with `can_start` / `step` / `should_stop` (+ `start`, `one_shot`).
- [x] All 12 wrapped (`hrlbot/options.py`).
- [x] **Safety shield** (`options.shield`): no illegal split, no step into kelp or a
      body, no unaffordable or colliding sprint; under danger, a step that fails
      Instinct's Tier A check is swapped for the reflex move. The one exception
      is RAM_TRADE stepping onto an enemy head on purpose.
- [x] **Interrupts**: when danger appears, the manager re-decides immediately.
- [x] Tests: `hrl_tests/test_hrl.py`, including a fuzz game where the manager picks
      random options and no illegal action may get through.

## Phase 3 — Scripted manager baseline

- [x] `manager.ScriptedManager`: doomed → RAM, DEFENSIVE_SPLIT, danger → ESCAPE,
      FORAGE, EXPLORE, which is exactly the old bot decomposed.
- [x] Benchmark: **46%** vs `mybot` (`mybot` vs itself: 48%). Saved in `hrl_train/results/baseline_scripted.txt`.
- [x] Its decisions are the demonstrations for Phase 5 (353k decisions, 128 games).

## Phase 4 — Train the weak options (bottom-up)

- [x] Scenario boards per option (`scenarios.py`).
- [x] Per-option rewards (`tune_options.py`): HUNT/PINCER = kills − deaths while
      running + result; ECON = team length + result; CAMP = length/turn + result.
- [x] Training. **Deviation:** instead of a small network per option, the
      options' parameters were tuned with the cross-entropy method (policy search)
      on full games, because the options are rule-based. The winner is re-checked
      on fresh seeds, and the defaults are kept if the "tuned" values don't
      hold up. Log: `hrl_train/results/tuning.txt`.
  - HUNT: deaths while hunting **12.1 → 8.3** per game, same kills (tuned, kept)
  - SPLIT_AND_PINCER: deaths **6.8 → 3.2**, same win rate (min length 8 → 11, kept)
  - ECON_SPLIT: defaults already best (**75%** wins on fresh seeds), kept
  - CAMP_CLUSTER: nothing better found, defaults kept (still weak)
- [x] Frozen: the tuned values are in `hrlbot/config.py`, marked `(tuned)`.

## Phase 5 — Train the manager

- [x] Observation: 23 situation features + the 12-option mask (`hrlbot/features.py`).
- [x] Action: option id, masked.
- [x] Decides when the option stops, on a danger interrupt, or every 4 turns.
- [x] Reward: length gained, kills, deaths, game result; SMDP discount
      `0.98 ** turns the option ran`.
- [x] Step 1: behaviour cloning (DQfD margin loss): **90%** agreement, 56% in a 32-game check.
- [x] Step 2: Double DQN self-play vs `mybot`, the scripted HRL bot, and past
      snapshots, 24 iterations. **No improvement**: 31–50% in 32-game checks.
      Log: `hrl_train/runs/main/log.txt`.
- [x] Maps, seeds and sides randomised every game.
- [x] Replay buffer, target net and epsilon schedule, driving the simulator.
- [ ] Run 2 with split credit (`--child-credit 1.0`): written, started, then stopped
      at your request before it produced results.

## Phase 6 — (Optional) joint fine-tuning

- [ ] Not done.

## Phase 7 — Evaluate

- [x] Learned vs `mybot` (`Instinct_Engine`): **40%** (48 games, all 8 maps,
      both sides): `hrl_train/results/final_learned.txt`. Scripted vs `mybot`: 46%.
      Against older HRL versions: only inside self-play training.
- [x] Option usage: the learned manager uses EXPLORE 54%, ESCAPE 36%, FORAGE 9%,
      and the rest almost never. HUNT, PINCER, RAM, PORTAL and ECON_SPLIT are
      **effectively unused**, which is exactly the bottom-up downside the paper
      warns about.
- [x] Death causes (in the evaluator): hit another body 2164, hit itself 1699,
      head-to-head 1683 over 48 games.
- [~] Real engine: 2 full games on `default_small` through the judge sandbox
      (no crashes, no CPU deaths). A multi-map real-engine check is still to do.
- [x] CPU check: see Phase 0.

## Phase 8 — Ship

- [x] Weights exported as plain Python lists (`hrlbot/manager_weights.py`).
- [x] Fallback: missing or broken weights → scripted manager; any exception →
      the next option → EXPLORE → emergency move. Never no action.
- [ ] `unswbc submit`: waiting for your go-ahead.

---

## Suggested next steps

1. **Run the split-credit training** (`python hrl_train/train_manager.py --child-credit 1.0 --iters 16`)
   and check that the manager learns to use ECON_SPLIT.
2. Or skip the learning for now: a scripted manager that also picks ECON_SPLIT
   whenever it can won 69–75% in tuning. That is the strongest bot found, but
   confirm it with a 48-game evaluation before trusting it.
3. Run 48+ games per evaluation. With 32-game checks, the noise (±9 points)
   is as large as the effects.

## Paper challenge → what we do about it

| Challenge from the survey | Our answer |
|---|---|
| Finding sub-goals automatically is hard | We don't: options are hand-picked from our existing engines |
| Non-stationarity when levels learn together | Bottom-up: freeze options, then train the manager; joint tuning is optional and slow |
| Credit assignment over long games | Manager decides rarely (per option, not per move); SMDP discounting. **Still the weak point:** splits went uncredited |
| Sample efficiency | Fast Python simulator, curriculum scenarios, behaviour cloning before RL |
| No good benchmark | Our own eval suite: every map, both sides, fixed baselines, option usage stats |

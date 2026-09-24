# Measurement rules (paid for in full, 2026-09-23/24)

## The rule

**Any harness result gets a control-group run on the shipped path before it is
read as evidence.**

- *Shipped path*: the code `mybot/main.py` actually executes, gates and budgets
  included — not the most capable path the modules can offer.
- *Control group*: the simplest thing that could work, run through the same
  harness. For defence that is "step where the most neighbours are open".

A number without both of those is a hypothesis, not a result.

## Why: four bugs, one shape

Every one was *evaluating the wrong object*. They were caught in this order,
and each cost more than the last.

| # | Bug | Effect |
|---|---|---|
| 1 | `escape_depth` read off the board BEFORE the move | every candidate scored the same; L2 was strictly worse than L1 |
| 2 | `l0_reflex` scored the landing tile against the pre-move board | our own tail still blocked enemy paths, so exposure was UNDER-counted |
| 3 | The death classifier tested exposure on the tile we stood on, not the one we landed on | mislabelled a box as a model gap |
| 4 | The harness called `ladder.decide()` (ungated) while the bot calls `decide_budgeted()` | **invalidated every result built on it** |

Bug 4 is the expensive one. It produced "Instinct beats the control 24 vs 21",
which survived two rounds of analysis because it was the answer we wanted. On
the shipped path the same comparison is 13 vs 21 — the other way round.

The fix is not "be more careful". It is the rule above.

## Corollaries

- **Report death causes, not survival.** 24 vs 21 stays inside noise until a few
  hundred matches; "head-to-head 13 -> 9, boxed 0 -> 6" told us what changed
  after 34.
- **A term that ablates to nothing may be measured wrong rather than useless.**
  `ram` looked null until it was cut from all three paths it feeds, and until
  the boxes that masked it were counted separately.
- **Saturating signals discriminate nothing.** `escape_depth` (capped at the
  horizon), `timed_space` (capped at its cap) and `free_volume` under heavy
  enemy cover all pinned to one value and stopped ranking anything.
- **Single-term ablation on a lexicographic key is systematically misleading.**
  A term decides every comparison where it disagrees with the terms below it, so
  the ones beneath are never consulted. Three terms changed sign here once
  something above them was removed:

  | term | with the term above it | without |
  |---|---|---|
  | `corridor` | -4 chamber / -2 open (looked essential) | +3 / +1 (costs survivals) |
  | `ram` | -2 (looked essential) | +6 / -1 |
  | `free_volume` | -6 (called "the whole engine") | +12 / +3 (harmful) |

  A single-term ablation does not measure that term. It measures that term PLUS
  the visibility it grants to everything beneath it. Two consequences:

  1. **Ablate cumulatively, from the top down.** Strip the highest term,
     re-measure, strip the next. Ablating singles measures a different engine
     each time. The final answer here - two terms - was invisible until the four
     above them had gone.
  2. **A lexicographic key is a filter chain, not a scoring function.** Anything
     above a term suppresses it entirely on every comparison where the upper
     term disagrees, so per-term evidence is not recoverable from it even in
     principle. If you want to know what each term contributes, use a weighted
     sum. A lexicographic key structurally cannot tell you.

- **Accuracy at the wrong moment loses to a crude signal at the right one.**
  The five-line greedy beats the nine-term engine because it applies a cheap
  "don't reduce your own options" cost on *every* turn, while Instinct's precise
  terms only run once danger is acute - by which time the options are gone.

## Scenario coverage caveat

The ladder (A0-A5) is biased toward open boards; A4 is the only chamber
scenario, 2 runs of 34. `--board chamber` builds the set this engine exists for:
six rooms joined by single-tile doorways.

**The open board never separated anything from the control**, across every
variant measured (everything sat in a 15-22 band around the control's 21). That
makes it a weak discriminator - NOT evidence that these boards are all alike.
Every real effect in this exercise showed up on the chamber board first.

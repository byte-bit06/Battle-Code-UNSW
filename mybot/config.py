"""Every tunable constant for the bot lives here. No magic numbers elsewhere.

IMPORTANT - how time works on the judge:
The judge runs Python inside a metered WebAssembly sandbox. Each turn gets
100,000,000 CPU points, and inside the sandbox time.perf_counter() is a
virtual clock where 1 ns == 1 point. So TIME_BUDGET_S = 0.050 means
"stop searching after 50M points". Measured costs (judge sandbox):
  * helper parsing + MOVE + ENDTURN        ~4-6M points per turn
  * every print/log line (write syscall)   ~2.5M points each
  * one BFS node expansion                 ~25-45k points
Exceeding 100M points kills the dragon ("exceeded CPU limit"), even if a
move was already printed. Locally (native Python) everything is ~30-50x
faster, so always check real costs with `unswbc run --sandbox -v`.
"""

# ---------------------------------------------------------------- time ----
TIME_BUDGET_S = 0.045        # virtual seconds on the judge (= 45M points)
LATE_RESERVE_S = 0.010       # skip long-range/exploration-goal work if less than this is left
FIRST_TURN_BUDGET_S = 0.012  # first turn of a process also pays ~40M points of imports
DEBUG = False                # when True, one indicator string per turn (costs ~2.5M points)

# --------------------------------------------------------------- split ----
# Foraging-first policy: a dragon splits ONLY when it is about to die with no
# legal move at all (a splitting parent does not move, so it survives the turn).
# Growth splitting is off until single dragons forage and survive well.
# NOTE: in testing, a team that never splits is eliminated more often.
ENABLE_SPLIT = False           # growth/redundancy splitting (owned by Memory_Engine)
ENABLE_EMERGENCY_SPLIT = True  # split instead of dying when no move is legal
SPLIT_TARGET_UNITS = 6         # keep at least this many dragons alive
SPLIT_MIN_LENGTH = 8           # only dragons this long bud off a child
SPLIT_CHILD_SIZE = 3           # child length (= spawn length); parent keeps the rest
SPLIT_LAST_ROUND = 470         # stop splitting near the end (tiebreak = longest dragon)

# ------------------------------------------------ Instinct_Engine (defence) --
# See instinct_engine.md. Instinct has absolute priority; other engines run on slack.
# Wiring: safety.py stays live. Instinct decides when it sees danger; in the
# clear, Forage keeps the turn (instinct_engine.md: "other engines run on slack").
# ON. MEASURED on the shipped path (tools/instinct_arena.py --ablate, 6 scenarios
# x 2 id orders x 4 seeds, 2026-09-24), survived / 34:
#                              chamber   open
#   Instinct (this config)       34/34   22/34     zero deaths on chamber
#   without the `options` term    6/34   14/34     the term the engine IS
#   without ram (l0 + hint)      34/34   21/34     no effect: unproven, kept as free
#   Instinct off (control)       17/34   21/34
# BOARD-DEPENDENT, and worth saying plainly: Instinct doubles survival on maps
# with kelp structure and is a wash on open ones (the open set never separated
# any variant from the control - it is a weak discriminator, not a null result).
# CPU: p50 34.2M, max 61.9M of the 100M limit; ~4M over not running it at all.
USE_INSTINCT = True          # master flag for the wiring in main.py
INSTINCT_PROFILE = False     # collect per-level timings (p50/p95) into ladder.TIMINGS
# MEASURED on the judge (probe, 2026-09-23): a turn that exceeds 100M points is
# killed as "no valid action" EVEN IF a valid action was already printed. So the
# ladder must stop itself; there is no safety net in re-submitting.
INSTINCT_L1_MAX_S = 0.020    # skip L1 if the turn has already used this much
INSTINCT_L2_MAX_S = 0.030    # ditto L2 (it is the expensive one)
INSTINCT_HARD_S = 0.060      # beyond this, stop everything and end the turn
ENABLE_INSTINCT = True
INSTINCT_MAX_SPRINT = 3       # Tier A: longest enemy sprint we plan against
INSTINCT_DANGER_DIST = 12     # no enemy head this close -> skip Instinct entirely.
                              # MEASURED: the fatal box is built 4-25 rounds (median 9)
                              # before death, so a tight gate never sees the turn that
                              # mattered (tools/instinct_walkback.py).
INSTINCT_HORIZON = 3          # joint-envelope horizon H (4.2)
INSTINCT_NODE_CAP = 80        # BFS nodes per call. MEASURED: a node costs 25-45k
                              # points on the judge, so every BFS is ~3M. The whole
                              # turn is 100M and Forage already spends ~30M.
INSTINCT_OPEN_DIST = 5        # "the open board" starts this far from our head (4.3)
INSTINCT_CORRIDOR_RADIUS = 10 # give up looking for a way out past this
INSTINCT_L1_CORRIDOR = True   # corridor count as a STANDING cost at L1, not an
                              # emergency gate: every death so far was a box built
                              # on turns nothing flagged as dangerous
INSTINCT_L1_CORRIDOR_RADIUS = 5   # cheap version: shorter search...
INSTINCT_L1_NODE_CAP = 32         # ...fewer nodes...
INSTINCT_L1_CORRIDOR_KMAX = 2     # ...and stop at 2. Most of the fatal gaps are
                                  # 1->2 (tools/instinct_walkback.py), and a third
                                  # min-cut pass costs a BFS on every open turn.
INSTINCT_L1_HORIZON = 2           # the frontier this standing cost aims at
INSTINCT_REGION_CAP = 48      # chamber / flood-fill cap
INSTINCT_SPACE_CAP = 32       # per-candidate timed space: enough to spot a trap
INSTINCT_SURVIVE_DEPTH = 6    # look-ahead when checking a grown body still has moves
INSTINCT_DEFENSIVE_SPLIT = True   # 4.8: split to survive a chamber
INSTINCT_ALLOW_SPRINT = False     # let the ladder consider 2-step sprints
INSTINCT_L2 = True                # run the control-layer level of the ladder
INSTINCT_RAISE = False            # tests/harness: re-raise what the ladder swallows.
                                  # A broad `except` hid a TypeError in l1_shallow for
                                  # two sweeps; every result was the L0 reflex alone.
INSTINCT_ABLATE = ""              # tests: zero key terms ("corridor", "options",
                                  # "ram"; comma-separate several)
# The key is four terms after measurement (instinct_tests/MEASUREMENT.md):
#   safe      hard filter
#   ram       UNRESOLVED. Ambiguous on both boards (no-ram was the best open-board
#             variant at 22/34), and its ablation is confounded because it also
#             feeds l0_reflex and the acute gate. Kept because it is near-free -
#             not because it is proven.
#   corridor  the one term with support on BOTH boards (no-corridor is joint-worst:
#             12/34 chamber, 15/34 open)
#   options   legal moves left after the step; what the greedy control does well

# ------------------------------------------------------------- rewards ----
R_LIVE = 100.0               # pearl visible now (or remembered)
R_PREDICTED = 80.0           # spawn predicted from a countdown
PEARL_ON_ROUTE_VALUE = 40.0  # each extra pearl the route eats before the target
NEARBY_PEARL_VALUE = 10.0    # each known pearl within Manhattan 2 of the target
TIMING_BONUS = 20.0
TIMING_EARLY_PENALTY = 5.0   # per turn we would have to wait
TIMING_LATE_PENALTY = 3.0    # per turn the pearl sits exposed before we arrive

# ------------------------------------------- cost weights (S formula) ----
C_D = 4.0    # travel, per move
C_R = 40.0   # enemy risk
C_T = 60.0   # trap risk
C_S = 30.0   # sprint cost, per segment spent
C_U = 50.0   # uncertainty

MIN_SCORE = 0.0              # below this, prefer exploration

# ------------------------------------------------------- spawn timing ----
# Verified in the engine (see forage_tests/ENGINE_FINDINGS.md): a countdown
# of T seen this turn spawns at the start of round now+T, so the earliest
# move that can eat it is move T + SPAWN_EAT_OFFSET (this turn's move = move 1).
SPAWN_EAT_OFFSET = 1
PRED_WAIT_MIN = -3           # ignore predicted targets we would reach > 3 turns late
PRED_WAIT_MAX = 8            # ... or more than 8 turns early

# ---------------------------------------------------- safety margins ----
L_RESERVE_MIN = 4            # never sprint below this length
TRAP_SAFE_FACTOR = 2.0       # want reachable area >= factor * length
FLOOD_CAP_MAX = 48           # flood fill never counts more tiles than this
ENEMY_RADIUS = 8             # enemies further than this (Manhattan) are ignored

SURVIVE_DEPTH_MAX = 30       # exact "can I keep moving" check depth
SURVIVE_NODE_CAP = 80        # nodes per survival check (only run in tight spaces)

# ----------------------------------------------------- search budgets ----
BFS_NODE_CAP = 360           # max tiles expanded by the per-turn BFS
BFS_RADIUS = 14              # max BFS depth
MAX_CANDIDATES = 24          # cheap-scored candidates kept
TOP_K_FLOODFILL = 4          # candidates that get the expensive checks

# ------------------------------------------------------------- memory ----
PEARL_STALE_ROUNDS = 30      # forget a remembered pearl after this many rounds unseen
PEARL_CLEANUP_EVERY = 10     # rounds between stale-pearl sweeps

# ----------------------------------------------- scavenging (Stage 3) ----
SCAVENGE_MIN_PEARLS = 3
SCAVENGE_RADIUS = 6
BEAM_WIDTH = 4
BEAM_HORIZON = 3
BEAM_EXPANSION_CAP = 12      # total pearl-to-pearl expansions per turn
LOCAL_BFS_CAP = 50           # nodes per pearl-to-pearl BFS inside the beam

# ------------------------------------------- timed approach / holding ----
HOLD_MAX = 6                 # max moves we search for an exact-timing approach
HOLD_NODE_CAP = 120

# ------------------------------------------------------ unknown terrain ----
UNKNOWN_STEP_UNCERTAINTY = 0.1

# ------------------------------------------------------------ explore ----
EXPLORE_FLOOD_CAP = 24
EXPLORE_STALE_BONUS = 3.0
EXPLORE_MOMENTUM_BONUS = 1.5

# ------------------------------------------------------ communication ----
ENABLE_SONAR = True          # one 32-bit message per turn (~2.5M points each)
SYM_RESEND_ROUNDS = 25       # re-announce the locked symmetry this often
CLAIM_ROUNDS = 4             # a teammate's claim on a pearl lasts this many rounds
REPORT_STALE_ROUNDS = 40     # forget teammates' death/cluster/enemy reports after this
R_REPORTED_PEARL = 60.0      # value per pearl in a teammate's report (it may be gone)

# --------------------------------------------------- teammates / enemies ----
TEAMMATE_RISK_FACTOR = 0.3   # teammates avoid our head too, so they're less dangerous
HEADING_RISK = 0.5           # extra risk for tiles straight ahead of an enemy head
HEADING_RAY = 4              # how far ahead of an enemy head that applies
ENEMY_TAIL_MARGIN = 1        # extra move before a known enemy tail cell counts as free

# ---------------------------------------------------- tiebreak holder ----
LONGEST_MIN_LENGTH = 10      # only dragons at least this long protect the tiebreak
LONGEST_MEMORY_ROUNDS = 30   # a teammate's LENGTH heartbeat counts for this long
CAREFUL_RISK_MULT = 2.0      # longest dragon: multiply C_R and C_T by this
CAREFUL_ESCAPE_FACTOR = 1.5  # ... and demand this much more escape room

# -------------------------------------------------------- long range ----
# OFF by default: in testing it pulled dragons away from nearby pearls and
# into kelp mazes (3-2 with it off vs 1-4 with it on, against the previous version).
ENABLE_FAR_GOALS = False
FAR_GOAL_RADIUS = 30         # remembered/reported/predicted targets up to this far
FAR_MIN_SCORE = 10.0

# ------------------------------------------------ directed exploration ----
EXPLORE_BLOCK = 8            # map split into 8x8 blocks for staleness tracking
ENABLE_EXPLORE_GOAL = False  # OFF by default for the same reason as ENABLE_FAR_GOALS
EXPLORE_GOAL_BONUS = 6.0     # bonus for the move heading to the exploration goal
EXPLORE_GOAL_KEEP = 25       # rounds to keep an exploration goal before re-picking

# ------------------------------------------------- adaptive budgets ----
SPARE_TIME_S = 0.030         # if this much budget is left, widen the searches
BEAM_WIDTH_BIG = 8
BEAM_HORIZON_BIG = 4
BEAM_EXPANSION_CAP_BIG = 24
HOLD_MAX_BIG = 8

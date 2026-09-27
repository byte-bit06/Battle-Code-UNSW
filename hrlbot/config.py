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
# Emergency split: with no legal move at all, split instead of dying (a
# splitting parent does not move, so it survives the turn). Growth splitting is
# the ECON_SPLIT option now (see the HRL section at the end).
ENABLE_EMERGENCY_SPLIT = True

# ------------------------------------------------ Instinct_Engine (defence) --
# See instinct_engine.md. In the HRL bot Instinct runs inside the ESCAPE option
# and the shield. MEASURED for mybot (tools/instinct_arena.py --ablate):
# Instinct doubles survival on boards with kelp structure (34/34 vs 17/34) and
# is a wash on open ones; CPU p50 34M, max 62M of the 100M limit.
INSTINCT_PROFILE = False     # collect per-level timings into ladder.TIMINGS
# MEASURED on the judge: a turn that exceeds 100M points is killed as "no valid
# action" EVEN IF a valid action was already printed, so the ladder stops itself.
INSTINCT_L1_MAX_S = 0.020    # skip L1 if the turn has already used this much
INSTINCT_HARD_S = 0.060      # beyond this, stop everything and end the turn
INSTINCT_MAX_SPRINT = 3       # Tier A: longest enemy sprint we plan against
INSTINCT_DANGER_DIST = 12     # no enemy head this close -> skip Instinct entirely.
                              # MEASURED: the fatal box is built 4-25 rounds (median 9)
                              # before death (tools/instinct_walkback.py).
INSTINCT_NODE_CAP = 80        # BFS nodes per call (a node costs 25-45k points on the judge)
INSTINCT_OPEN_DIST = 5        # "the open board" starts this far from our head (4.3)
INSTINCT_CORRIDOR_RADIUS = 10 # give up looking for a way out past this
INSTINCT_REGION_CAP = 48      # flood-fill cap
INSTINCT_DEFENSIVE_SPLIT = True   # 4.8: split to survive a chamber
INSTINCT_RAISE = False            # tests/harness: re-raise what the ladder swallows
INSTINCT_ABLATE = ""              # tests: zero key terms ("options", "ram")
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

# ================================================================= HRL ====
# Hierarchical RL (HRL_CHECKLIST.md). Every turn the AI (the manager) picks an
# option and the option gives that turn's move; a safety shield vetoes anything
# illegal. The options carry no rules about WHEN to use them - those were
# removed so the AI decides (round, length, which teammate to feed, ...).
# Values marked (tuned) are how an option plays, set by hrl_train/tune_options.py.
HRL_MANAGER = "learned"      # "learned" (manager_weights.py) or "scripted"
HRL_EPSILON = 0.0            # training only: random feasible option this often
HRL_SHIELD_TIER_A = True     # under danger, veto moves that fail Instinct's Tier A check

# ------------------------------------------------------------ options ----
CAMP_RADIUS = 8              # CAMP_CLUSTER: spawn tiles considered around us
CAMP_WINDOW = 12             # ...whose countdown is at most this
PORTAL_RADIUS = 10           # PORTAL_TRAVEL: known portal entries this close
PORTAL_MIN_GAIN = 10         # exit must be this many rounds staler than here
PORTAL_UNKNOWN_GAIN = 30     # value of a portal whose far end we have never seen
HUNT_AREA_CAP = 40           # flood-fill cap when measuring the enemy's room
HUNT_W_SQUEEZE = 1.327       # (tuned) weight on shrinking the enemy's room
HUNT_W_OWN = 0.174           # (tuned) weight on our own room
HUNT_W_CLOSE = 1.911         # (tuned) weight on reaching the tile ahead of the enemy
HUNT_AHEAD = 0               # (tuned) aim this many steps in front of the enemy head
                             # (0 = its head itself: the tuner preferred plain pursuit)
HUNT_MEMORY = 3              # follow the last sighting for this many rounds
ECON_CHILD = 3               # (tuned) ECON_SPLIT child length
# How our dragons get information and talk to each other

## 1. What a single dragon knows

Every dragon runs its **own copy** of our program, in its own process. Dragons share
**no memory**: a variable in one dragon's program doesn't exist in any other dragon.

A dragon has exactly three sources of information:

| Source | What it gives | Where it lives in our code |
|---|---|---|
| **Vision** (every turn) | The 7×7 square around its head: pearls, countdowns, kelp/portal edges, and every dragon segment (team, id, head or not, facing direction). | `snapshot.build()` turns it into a `Snapshot` |
| **Its own memory** (for its lifetime) | Everything it has *ever* seen: countdowns (wound forward each round), pearls, kelp, portals, which 8×8 blocks it has explored, the symmetry it worked out. | `memory.WorldMemory`, created once in `main()` |
| **Sonar messages** from other dragons | Short 32-bit reports (see below). | `comms.Comms.receive()` writes them into memory |

A split child is a **brand-new process**. It starts with empty memory, and the only way
it can learn anything its parent knew is through sonar.

## 2. How sonar physically works (engine rules)

- Once per turn a dragon may send **one unsigned 32-bit integer** (`ct.send_sonar(n)`).
- After the dragon's move, the signal leaves its head **in the direction it now faces**.
  It travels in a straight line, wraps around the map and passes through portals.
- It stops at the **first kelp edge or dragon segment** it hits. The dragon it hits
  receives it, whatever its team, and it could even be the sender.
  If it hits nothing within width + height tiles, it's lost.
- The receiver reads it at the start of its next turn (`ct.get_sonar_messages()`).
  A higher-id receiver gets it later in the same round; a lower-id one gets it next round.
- **No sender, team or position is attached.** Enemies hear our messages and we hear theirs.

So sonar is a *directional, one-hop, anyone-can-intercept* broadcast. You can't address a
specific teammate. Whoever happens to be in the line of fire receives it.

## 3. Our message format

```
 bit 31      28 27        22 21        16 15         8 7          0
    [  type:4  |    x:6     |    y:6     | payload:8  |  check:8   ]
```

- `x`, `y`: a tile (6 bits each, which covers the biggest 64×64 map).
- `check`: a keyed hash of the other 24 bits. A number that fails the check is ignored.
  This filters out enemy traffic: a random number passes about 1 time in 256,
  and every message is only advice, so a bad one can never force an illegal move.

| Type | Meaning | x, y | payload | What the receiver does |
|---|---|---|---|---|
| `SYM` (1) | "The map's symmetry is V/H/R" | unused | 1 V, 2 H, 3 R | Locks its symmetry tracker, unless its own evidence already ruled that option out. It can then predict pearls on the mirror half. |
| `DEATH` (2) | "A dragon just died here" | first drop tile | pearls seen appearing | Stores a report; it becomes a long-range target (`far_goal`). |
| `CLUSTER` (3) | "Group of pearls here" | densest pearl | count | Same as `DEATH`, at lower urgency. |
| `CLAIM` (4) | "I'm going for this pearl" | target | my distance | If the claimant is closer, the receiver gives up that pearl for 4 rounds. |
| `LENGTH` (5) | Heartbeat | unused | my length | Tracks the longest teammate heard; used to decide who guards the tiebreak. |
| `ENEMY` (6) | "Enemy head here" | head | its visible length | Long-range targets near a reported enemy get a risk penalty. |

## 4. What gets sent each turn (`comms.Comms.choose`)

Only one message fits per turn, so we pick by priority:

1. **DEATH**, if this dragon just watched pearls appear where another dragon's body was.
   This is the most time-critical, because death drops get eaten fast.
2. **SYM**, once the symmetry is locked. It's re-sent every 25 rounds so that new
   children and teammates who walk into the beam get it.
3. Otherwise it **rotates** through CLAIM (our current target), LENGTH,
   CLUSTER (if we can see 3 or more pearls together) and ENEMY (if one is in view),
   so none of them starves.

Each message costs about 2.5M CPU points (it's printed), out of the 100M per turn.

## 5. How the information is used

- **Teammates stop chasing the same pearl.** The contention rule already gives a pearl to
  whoever is closer (lower id on a tie), and CLAIM lets a dragon give up a pearl
  before it can even see its rival.
- **Children and distant dragons learn the symmetry** without collecting their own evidence.
  That unlocks mirrored countdowns and kelp for the half of the map they've never seen.
- **Death drops attract help from beyond vision** through `DEATH` reports and `far_goal()`.
- **Tiebreak protection.** A dragon that is at least 10 long and hasn't heard of a longer
  teammate in the last 30 rounds treats itself as the tiebreak holder. It then:
  - doubles its risk and trap weights;
  - needs 1.5× the escape room;
  - never races an enemy for a pearl;
  - never sprints.

## 6. Limits worth knowing

- A message only reaches whoever is in the straight line ahead. Two teammates facing
  away from each other never hear each other.
- Enemies can hear everything, including our claims and death reports.
  Nothing we send is secret.
- An enemy body in the way intercepts the message: the enemy gets it and we don't.
- Right now we only have the dragons the map starts with (plus emergency-split children),
  so there are few listeners. Sonar becomes much more useful once splitting is turned
  back on.
- Ideas for the swarm team: face-aware sending (check whether a teammate is in the beam
  before choosing the message), relaying (re-sending important reports we heard),
  and encoding the team's longest length in `SYM` messages too.

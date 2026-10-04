#pragma once

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <vector>

namespace bc {

// Direction order matches the engine: North is y-1.
enum Dir : int { N = 0, E = 1, S = 2, W = 3 };
inline constexpr int DX[4] = {0, 1, 0, -1};
inline constexpr int DY[4] = {-1, 0, 1, 0};
inline constexpr char DCH[4] = {'N', 'E', 'S', 'W'};
inline constexpr int INF = 1 << 29;

// Movement under the live rules: a dragon of length L takes its first ceil(L/4) steps
// of a turn free and pays one tail segment for each step after that; it must keep 2.
inline int freeSteps(int L) { return (L + 3) / 4; }
inline int maxSteps(int L) { return freeSteps(L) + std::max(0, L - 2); }

// The queen is the team's first starting dragon: id 0 for team A, 1 for team B.
// Its length is the first round-500 tiebreak.
inline int queenIdOf(char team) { return team == 'A' ? 0 : 1; }

inline int dirFromChar(char c) {
    switch (c) {
    case 'N': return N;
    case 'E': return E;
    case 'S': return S;
    case 'W': return W;
    }
    return -1;
}

// Every tunable number lives here. These are plain hand-set starting values,
// not tuned ones: tuning them is the first thing to try.
struct Params {
    // pearl value
    double gamma = 0.80;              // discount per move of distance
    double eatBonus = 1.0;            // eating right now
    double exploreValue = 0.15;       // per never-seen tile
    double seenDecay = 0.97;          // belief a pearl we saw is still there, per round
    double spawnDecay = 0.985;        // belief an unseen spawned pearl is still there, per round
    double enemyCloserFactor = 0.5;   // pearl an enemy head reaches first
    int horizon = 48;                 // BFS depth considered
    int maxRivalFields = 12;          // distance fields computed for the nearest visible heads
    int maxDepth = 10;                // lookahead cap for the anytime search
    double leanMargin = 0.045;        // < this much turn clock left at decide(): one-step turn only

    // safety
    int spaceMargin = 3;              // reachable tiles needed: spaceFactor * length + margin
    double spaceFactor = 2.0;         // eating keeps the tail still, so plain length is optimistic
    double wSpace = 0.6;              // mild preference for open space
    double wDanger = 1.5;             // per own segment, tile next to an enemy head
    double wPocket = 1.5;             // entering a tile with a single way onward
    double wReverse = 1.5;            // entering a dead end we can only leave by a reverse split
    double wBlind = 2.0;              // portal into unseen tiles where dragons were seen lately
    double wBlindQuiet = 0.01;        // portal into unseen tiles with no recent sightings
    int blindMemory = 6;              // rounds a sighting near a portal exit stays relevant
    double wPortalLoiter = 1.0;       // ending a move on a tile beside a portal
    double wCramped = 3.0;            // space below need (but >= length): penalty * missing share, pearls still count

    // anti-loop and exploration
    int recentMemory = 24;            // head tiles remembered per dragon
    double wRevisit = 0.25;           // per remembered visit of the tile we would step on
    int loopHits = 3;                 // head on a tile this many times in memory: explore mode
    int exploreTurns = 20;            // explore mode lasts this long (or until the target is reached)
    int staleAge = 40;                // a tile unseen this many rounds is worth re-exploring
    double staleValue = 0.06;         // explore value of a stale tile (never-seen: exploreValue)
    double wExploreTarget = 2.5;      // pull toward the explore-mode target (gammaFar discount)
    int claimRadius = 3;              // a closer teammate this near a pearl claims most of it...
    double claimNear = 0.3;           // ...keep this share
    double claimFar = 0.7;            // closer teammate further away: keep this share

    // portal scouting: one scout per unknown portal, reports what it found
    double wScout = 1.5;              // base value of scouting an unknown portal
    double scoutLenCost = 0.08;       // per segment: long dragons have more to lose
    int scoutRadius = 6;              // a lower-id non-queen teammate this close scouts instead
    int reportTurns = 3;              // rounds a scout broadcasts its report after crossing
    int reportWait = 10;              // a suspected crossing with no report after this long: portal is bad
    double wPortalReport = 1.0;       // per point of reported portal quality, on crossing it

    // phases
    int earlyEnd = 120;               // hunting squads switch on here ("mid game")
    int midEnd = 400;                 // late game: growers stop splitting, play safest

    // roles: growers (the starting dragons, or anyone long) farm and stay safe;
    // the swarm (split children) escorts, hunts and scavenges.
    int promoteLen = 10;              // any dragon this long plays as a grower
    int growerKeepBase = 4;           // grower keeps at least base + round/keepEvery segments
    int growerKeepEvery = 30;
    int growerChild = 2;              // growers bud off children this long
    double growerDanger = 3.0;        // extra danger multiplier for growers
    int swarmSplitLen = 4;            // swarm dragons split in half at this length (tested: raising it starves the army)
    int swarmSplitLenEarly = 4;       // ...before earlyEnd (kept separate so early and later splitting can be tuned apart)
    int queenSplitUntil = 60;         // the queen splits only in the opening, to build the first army (Phase 2;
                                      // vD: 500, so she never grew: median max length 4). 0 never; 500 always.
    int queenKeepLen = 4;             // a queen split always leaves her at least this long
    int queenSplitMinLen = 4;         // ...only when at least this long
    int queenCrowdRadius = -1;        // ...and no teammate head this close to her (-1: off; 3 tested worse)
    int queenReverse = 1;             // a truly boxed-in queen may reverse-split (a 2-long queen beats a dead one)
    int splitEnemyDist = 2;           // no split with an enemy head this close
    int splitRoom = 8;                // both halves need this much reachable room to split
    int splitQueenDist = -1;          // no split whose child (our old tail) lands this close to the queen or a grower (-1: off; 3 tested level, 4-6 much worse)
    int unitsPerTiles = 1;            // army cap: max(minUnitCap, tiles / unitsPerTiles) dragons (1: just the unit limit; 20-40 tested much worse)
    int minUnitCap = 6;
    int outnumberedTurns = 5;         // visible enemies must outnumber allies this many turns in a row to unlock splitting

    // economy / attrition
    int growerMinUnits = 40;          // growers exist only once the army is this big...
    int growRound = 300;              // ...or from this round
    int lateSplitUnits = 20;          // after growRound the swarm splits only below this many units
    int tradeMinUnits = 4;            // below this many units we do not trade heads
    int tradeSlack = 1;               // trade if own length <= enemy visible length + slack
    int survivalUnits = 3;            // at or below: extra caution
    double survivalDanger = 3.0;

    // squads
    int squadSize = 3;                // per enemy target: 1 attacker + (squadSize-1) supporters
    int escortCount = 2;              // swarm dragons that stay around a visible grower (Phase 2: was 3)
    int escortRadius = 5;             // enemy head this close to a grower is a threat
    int escortRing = 4;               // escorts hold this distance from the grower (Phase 2: was 3, too close)
    int supportRing = 3;              // supporters hold this distance from the target, ready to eat
    double wHunt = 1.5;
    double wEscort = 0.8;
    double wSupport = 0.6;

    // head-on trades and sprints (a MOVE by a dragon of length L goes at most maxSteps(L) steps)
    int localRadius = 3;              // heads this close (Chebyshev) to a trade site count as local
    int reachCap = 3;                 // enemy sprint reach considered: min(maxSteps(visible length), cap)
    double wExposed = 1.2;            // per own segment, ending within an enemy head's reach
    double exposedFavour = 0.35;      // multiplier when we have the local numbers there
    int sprintMax = 4;                // our own sprint trades: at most this many steps
    int sprintTrades = 1;             // 0: no sprint trades
    // How enemy heads count as danger:
    // 0: next to an enemy head, unless we would trade with it; sprint reach ignored
    // 1: anywhere inside an enemy's sprint reach, reduced where we have the local numbers
    // 2: like 0, plus sprint-reach danger only where enemies outnumber us
    int exposureMode = 1;

    // tactical split thresholds
    int tacticalSplitSlack = 2;       // skip tactical split if enemy is shorter than L - slack
    int tacticalSplitMinThreat = 8;   // but always tactical split if enemy is this long

    // end-game feeding: the queen's length breaks a round-500 tie. A small dragon walks
    // to the lowest-id teammate it can see below its own id (our queen whenever it is in
    // view) and dies by its head, dropping ceil(L/2) pearls there. The queen never feeds.
    int feedRound = 400;
    int lateGameRound = 350;          // when late game behavior kicks in
    int feedStop = 490;               // later sacrifices cannot be eaten in time
    int feedMargin = 4;
    int feedMaxLen = 6;               // only small dragons feed
    int feedDist = 1;                 // die when this close to a tile next to the big head
    double wFeed = 3.0;

    // hot beds (fountains): fast-respawning beds, valued as a long-range pull
    // proportional to their yield rate (pearls per round).
    int hotObs = 3;                   // a bed is hot once this many countdowns were seen on it...
    int hotGap = 10;                  // ...and none exceeded this
    double hotRate = 0.1;             // mean respawn gap <= 10 rounds
    double wHot = 2.0;
    double gammaFar = 0.93;           // discount per move for the long-range pull
    int hotYield = 4;                 // yield a hot bed only to a teammate this close to it

    // free steps: each turn a dragon walks its ceil(L/4) free steps, one decision per step
    int freeSprint = 1;               // 0: always one step
    double stopMargin = 0.5;          // stop early when the next free step scores this much worse
    double firstStepShare = 0.5;      // share of the turn's search budget for the first step

    // personal space for the queen (teammates)
    int queenSpaceRadius = 2;         // non-queen dragons pay for ending this close (Chebyshev) to the queen
    double wQueenSpace = 1.5;         // ...per step inside the radius
    int queenBoxRadius = 6;           // within this range we check our move does not shrink the queen's room
    double wQueenBox = 6.0;           // moving so the queen's room drops below her need
    int feedAhead = 2;                // feeders die this many tiles ahead of the queen's facing

    // tiebreak and anchor (plan Phase 1). Round-500 order: queen length, then longest
    // dragon, then total length. From tiebreakRound we stop splitting and grow ONE anchor:
    // our queen if she is alive, otherwise our longest dragon.
    int tiebreakRound = 300;          // from here: no splits (but the boxed-in escape), feed only the anchor
    int statusMemory = 30;            // rounds a teammate's length (radio or vision) stays fresh
    int rivalMemory = 60;             // rounds an enemy sighting stays fresh
    int feedLead = 3;                 // feed only while anchor length <= rival length + feedLead
    int feedEnemyDist = 4;            // no feeding with an enemy head this close (Chebyshev) to the drop spot
    int anchorEscortRing = 5;         // escorts hold this distance from the anchor

    // our queen: its only job is to stay alive to be fed late. It never trades, never
    // crosses a portal, and steers by its own sonar away from enemies.
    double queenDanger = 5.0;         // danger multiplier for the queen (growers use growerDanger)
    int queenThreatRadius = 5;        // enemy head this close to our queen: teammates go for it
    // queen survival (plan Phase 2). On the server she died head-on with ~3 enemies and no
    // teammate within 3 tiles: being reachable by several heads at once is what kills her.
    double wQueenReach = 2.0;         // per enemy head that can reach the tile this round
    double wQueenMulti = 4.0;         // extra per additional enemy head that can reach it
    int queenAlarmRadius = 5;         // 2+ enemy heads this close (Chebyshev): flee mode
    double wQueenFlee = 3.0;          // flee mode: value of distance from the alarm heads
    double wQueenRoom = 1.0;          // the queen values escape room (reachable tiles) on top of wSpace
    double wQueenAdjacent = 6.0;      // a teammate ending on one of the queen's 4 neighbour tiles
    int sonarMemory = 4;              // rounds a sonar echo for one direction stays relevant
    double wSonarEnemy = 3.0;         // moving the way a recent ray hit an enemy
    double wSonarAlly = 0.5;          // moving the way a recent ray hit a teammate
};

inline Params const kParams{};

// Radio packets (sonar values). Sonar carries no sender or team, so every packet
// we send is tagged: bits 60-63 type, bits 52-59 a team signature, bits 0-51 payload.
// Anything whose signature does not match is ignored (enemy rays reach us too).
enum PacketType : uint64_t { PKT_HOT = 1, PKT_PORTAL_END = 3, PKT_PORTAL_REPORT = 4, PKT_STATUS = 5 };
// PKT_STATUS payload: dragon id (16 bits) << 20 | its length (12 bits) << 8.
inline uint64_t teamSig(char team) { return team == 'A' ? 0xB7u : 0x5Du; }
inline uint64_t packet(PacketType type, char team, uint64_t payload) {
    return (static_cast<uint64_t>(type) << 60) | (teamSig(team) << 52) | (payload & ((1ULL << 52) - 1));
}
inline bool packetOk(uint64_t msg, char team) { return ((msg >> 52) & 0xFF) == teamSig(team); }
inline uint64_t packetType(uint64_t msg) { return msg >> 60; }
inline uint64_t packetPayload(uint64_t msg) { return msg & ((1ULL << 52) - 1); }

// Seconds since process start. In the judge's sandbox the clock is virtual and
// advances 1 ns per CPU point spent (unswbc sandbox.py: now = spent + slept_ns),
// so the 100M-point turn budget is 0.1 s on this clock.
inline double clockNow() {
    static auto const start = std::chrono::steady_clock::now();
    return std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
}

// Seconds of that clock the search may spend per turn: 0.075 = 75M of the 100M
// points. Test builds may override it to keep native local games short.
#ifndef BC_TURN_BUDGET
#define BC_TURN_BUDGET 0.075
#endif

}  // namespace bc

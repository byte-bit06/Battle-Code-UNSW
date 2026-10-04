// Every dragon runs its own copy of this program. Each turn: read what the dragon
// sees (io.hpp), update what it knows about the map (world.hpp), pick an action
// (policy.hpp) and write it out in a single write.
#include <cstring>

#include "io.hpp"
#include "policy.hpp"
#include "world.hpp"

namespace bc {

// Portal report payload: pid (16 bits) << 20 | pearls (4) << 16 | space (6) << 10 | enemy heads (2) << 8.
inline uint64_t reportPayload(int pid, int pearls, int space, int enemies) {
    return (static_cast<uint64_t>(pid & 0xFFFF) << 20) | (static_cast<uint64_t>(std::min(pearls, 15)) << 16) |
           (static_cast<uint64_t>(std::min(space, 63)) << 10) | (static_cast<uint64_t>(std::min(enemies, 3)) << 8);
}

// Quality of a portal's far side from a report: pearls and room are good, enemy heads
// and a cramped landing are bad. Clamped to [-3, 3].
inline double reportScore(int pearls, int space, int enemies) {
    double g = 0.5 * pearls + space / 20.0 - 1.5 * enemies - (space < 8 ? 2.0 : 0.0);
    return std::max(-3.0, std::min(3.0, g));
}

// What a scout sees on the far side of the portal it just crossed.
inline void surveyHere(World const& w, int& pearls, int& space, int& enemies) {
    pearls = enemies = 0;
    for (VisTile const& v : w.t.tiles) pearls += v.pearl;
    for (World::Seen const& s : w.others) enemies += s.team != w.init.team;
    std::vector<int> blk(w.board.NC, 0);
    for (int c = 0; c < w.board.NC; c++)
        if (w.occ[c] >= 0) blk[c] = INF;
    markBody(blk, w.body, w.t.length);
    Nav nav;
    space = nav.flood(w.board, w.head, blk, 64);
}

}  // namespace bc

int main() {
    using namespace bc;
    clockNow();  // start the meter: setup on the first turn counts against it
    std::setvbuf(stdout, nullptr, _IOFBF, 1 << 16);
    Reader in;
    Init init;
    if (!readInit(in, init)) return 0;

    World world;
    world.start(init);
    Out out;
    Turn turn;
    bool first = true;
    while (readTurn(in, turn)) {
        // The first turn's clock started with the process (setup counts); later ones on arrival.
        double turnStart = first ? 0.0 : clockNow();
        first = false;

        world.observe(turn, kParams);

        // --- RADIO RECEIVER: parse signals from teammates (signed packets only) ---
        for (uint64_t msg : turn.msgs) {
            if (!packetOk(msg, init.team)) continue;  // an enemy ray, or noise
            uint64_t type = packetType(msg);
            uint64_t payload = packetPayload(msg);
            if (type == PKT_HOT) {
                int c = static_cast<int>(payload & ((1ULL << 20) - 1));
                if (c >= 0 && c < world.board.NC) {
                    world.board.bed[c] = 1;
                    world.board.gapMin[c] = 1;
                    world.board.gapMax[c] = 10;
                }
            } else if (type == PKT_PORTAL_END) {
                int c = payload & ((1ULL << 19) - 1);
                int orient = (payload >> 19) & 1;
                int pid = (payload >> 20);
                if (c >= 0 && c < world.board.NC) {
                    bool changed = world.notePortal(pid, orient, world.board.X(c), world.board.Y(c));
                    if (changed) world.board.rebuild();
                }
            } else if (type == PKT_CLAIM) {
                int tile = static_cast<int>((payload >> 20) & 0xFFFF);
                int id = static_cast<int>((payload >> 4) & 0xFFFF);
                if (id != init.id && tile < world.board.NC) world.noteClaim(tile, id, turn.round);
            } else if (type == PKT_STATUS) {
                int id = static_cast<int>((payload >> 20) & 0xFFFF);
                int len = static_cast<int>((payload >> 8) & 0xFFF);
                if (id != init.id) World::noteLen(world.teamLens, id, len, turn.round, true);
            } else if (type == PKT_PORTAL_REPORT) {
                int pid = static_cast<int>((payload >> 20) & 0xFFFF);
                int pearls = static_cast<int>((payload >> 16) & 0xF);
                int space = static_cast<int>((payload >> 10) & 0x3F);
                int enemies = static_cast<int>((payload >> 8) & 0x3);
                World::PortalInfo& pi = world.infoFor(pid);
                pi.score = reportScore(pearls, space, enemies);
                pi.round = turn.round;
            }
        }

        // --- RADIO TRANSMITTER: broadcast known information ---
        // The queen keeps its rays for its own sonar (below), so it broadcasts nothing.
        int broadcastCount = world.isQueen() ? 4 : 0;
        char dirs[4] = {'N', 'E', 'S', 'W'};

        // Priority 0: a scout reports on the portal it just came through, on two rays.
        if (broadcastCount < 4 && world.crossedPid >= 0 && turn.round <= world.reportUntil) {
            int pearls, space, enemies;
            surveyHere(world, pearls, space, enemies);
            World::PortalInfo& pi = world.infoFor(world.crossedPid);
            pi.score = reportScore(pearls, space, enemies);
            pi.round = turn.round;
            uint64_t msg = packet(PKT_PORTAL_REPORT, init.team, reportPayload(world.crossedPid, pearls, space, enemies));
            for (int k = 0; k < 2 && broadcastCount < 4; k++) out.ping(msg, dirs[broadcastCount++]);
        } else if (turn.round > world.reportUntil) {
            world.crossedPid = -1;
        }

        // Priority 0b: our length, so teammates agree on the tiebreak anchor (Phase 1).
        uint64_t status = packet(PKT_STATUS, init.team,
                                 (static_cast<uint64_t>(init.id & 0xFFFF) << 20) |
                                 (static_cast<uint64_t>(std::min(world.t.length, 4095)) << 8));
        // Phase 3: on odd rounds that ray carries our target region instead (as one of its
        // tiles), so teammates spread over the map rather than all chasing the same area.
        bool claimTurn = turn.round % 2 == 1 && world.targetRegion >= 0 &&
                         world.targetRegion < static_cast<int>(world.regions.tiles.size());
        if (broadcastCount < 4) {
            if (claimTurn) {
                int tile = world.regions.tiles[world.targetRegion].front();
                out.ping(packet(PKT_CLAIM, init.team, (static_cast<uint64_t>(tile & 0xFFFF) << 20) |
                                                          (static_cast<uint64_t>(init.id & 0xFFFF) << 4)),
                         dirs[broadcastCount++]);
            } else {
                out.ping(status, dirs[broadcastCount++]);
            }
        }

        // Priority 1: Hotspots
        for (int c = 0; c < world.board.NC && broadcastCount < 4; c++) {
            if (world.board.bed[c] == 1 && world.board.gapMax[c] > 0) {
                double rate = 2.0 / (world.board.gapMin[c] + world.board.gapMax[c]);
                if (rate >= kParams.hotRate) {
                    uint64_t msg = packet(PKT_HOT, init.team, static_cast<uint64_t>(c));
                    out.ping(msg, dirs[broadcastCount++]);
                }
            }
        }

        // Priority 2: Portal Maps
        if (broadcastCount < 4 && !world.portalEnds.empty()) {
            int offset = turn.round % world.portalEnds.size();
            auto const& pe = world.portalEnds[offset];
            int pid = pe.first;
            for (auto const& end : pe.second) {
                if (broadcastCount >= 4) break;
                int c = world.board.id(end.x, end.y);
                uint64_t msg = packet(PKT_PORTAL_END, init.team,
                                      ((uint64_t)(pid & 0xFFFF) << 20) | ((uint64_t)end.orient << 19) | (uint64_t)c);
                out.ping(msg, dirs[broadcastCount++]);
            }
        }

        Params turnParams = kParams;

        // --- ADAPTIVE MACRO STRATEGY ---
        int visibleEnemies = 0;
        int visibleAllies = 0;
        for (auto const& s : world.others) {
            if (s.team != init.team) visibleEnemies++;
            else visibleAllies++;
        }

        // Only a sustained disadvantage unlocks unlimited splitting: one turn of a noisy
        // local count used to flip it back and forth.
        static int outnumberedStreak = 0;
        outnumberedStreak = visibleEnemies > visibleAllies ? outnumberedStreak + 1 : 0;
        if (outnumberedStreak >= turnParams.outnumberedTurns) {
            // We are outnumbered! Focus on re-populating and safety.
            turnParams.lateSplitUnits = 1000; // Allow unlimited splitting to rapidly reproduce
            turnParams.wDanger *= 1.5;     // Play safer
            turnParams.wExposed *= 1.2;
        } else {
            // We have the numbers! Focus on aggression and building large snakes.
            turnParams.lateSplitUnits = 0; // Stop splitting, consolidate length
            turnParams.wDanger *= 0.8;     // Play aggressively
        }

        // --- LATE GAME OVERRIDES ---
        if (turn.round >= turnParams.lateGameRound) {
            turnParams.wDanger *= 2.0;        // Double fear of enemy heads
            turnParams.wExposed *= 1.5;       // Stay out of open territory
            // Feeding keeps its own start (feedRound) and only ever feeds the anchor (Phase 1):
            // starting at lateGameRound fed whoever was nearby, 18 suicides a game on the server.
            turnParams.lateSplitUnits = 0;    // Effectively stop splitting so snakes grow huge
        }

        // --- DECIDE: the first step is the usual full decision (splits, trades, sprint
        // trades). A dragon of length L moves ceil(L/4) steps free, so after a plain step
        // it keeps walking, one decision per step, while the next step is not worse. ---
        double turnEnd = turnStart + BC_TURN_BUDGET;
        int freeN = turnParams.freeSprint ? freeSteps(world.t.length) : 1;
        double share = freeN > 1 ? turnParams.firstStepShare : 1.0;
        Policy policy(world, turnParams, turnStart + BC_TURN_BUDGET * share, turnEnd);
        Choice c = policy.decide();
        std::string why = c.why;
        if (c.split) {
            out.split(c.n);
            world.body.resize(std::max(2, world.t.length - c.n));
        } else if (!c.sprint.empty()) {
            out.moveSeq(c.sprint);  // sprint trade: we die with the target
        } else {
            std::string path(1, DCH[c.dir]);
            bool more = c.dest >= 0 && !c.terminal;
            if (c.dest >= 0) world.stepTo(c.dest, c.dir, c.eat, turnParams);
            else if (c.dest == -2) {
                world.noteStep(world.head, c.dir, turnParams);  // blind portal: report what is there
                world.advanceBody(-1, c.eat);
            }
            double prevScore = c.score;
            for (int i = 1; i < freeN && more; i++) {
                double stepEnd = turnStart + BC_TURN_BUDGET * (share + (1.0 - share) * i / (freeN - 1));
                Policy step(world, turnParams, stepEnd, turnEnd, true);
                Choice s = step.decide();
                // Stop where the next step is illegal, vetoed, or clearly worse than here.
                if (s.dest < 0 || s.split || s.score < -500 || s.score < prevScore - turnParams.stopMargin) break;
                path += DCH[s.dir];
                world.stepTo(s.dest, s.dir, s.eat, turnParams);
                prevScore = s.score;
                why += "+" + s.why;
                more = !s.terminal;
            }
            if (path.size() == 1) out.move(c.dir);
            else out.moveSeq(path);
        }
        if (world.isQueen()) {
            // Queen sonar: one ray a turn, turning through the directions; next turn's
            // echo says what it met first (World::observe). A ray opposite our facing
            // would leave from the tail instead, so that direction is skipped.
            int d = turn.round % 4;
            if (d == (world.t.dir ^ 2)) d = (d + 1) % 4;
            out.ping(status, DCH[d]);  // the echo works whatever the value: carry our status
            world.rayDir = d;
        }
        out.log("r" + std::to_string(turn.round) + " " + why +
                " depth=" + std::to_string(policy.depthReached()) +
                " ms=" + std::to_string(static_cast<int>((clockNow() - turnStart) * 1000)) +
                " L=" + std::to_string(turn.length) +
                " body=" + std::to_string(world.body.size()) +
                " anchor=" + std::to_string(world.anchorId(turnParams)) +
                " rival=" + std::to_string(world.rivalLen(turnParams)));
        out.flush();
    }
    return 0;
}

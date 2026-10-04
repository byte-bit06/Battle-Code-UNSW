#pragma once

#include "nav.hpp"
#include "world.hpp"

namespace bc {

struct Choice {
    bool split = false;
    int dir = N;
    int n = 0;
    int dest = -1;
    bool eat = false;
    double score = -1e18;
    std::string why;
    // search bookkeeping
    std::string sprint;      // multi-step MOVE (a sprint trade), empty for one step
    bool terminal = false;   // trade or vetoed: nothing to search past it
    double stepTerm = 0;     // what this step alone earns (eat bonus minus danger)
    int newL = 0;
};

// Roles are decided locally every turn from shared facts, so teammates agree
// without talking:
//   grower  - a starting dragon, or anyone long. Farms, buds off short children, avoids fights.
//   swarm   - everyone else. Escorts visible growers, forms squads on long enemies:
//             the closest swarm dragon trades heads, the next (squadSize-1) wait a few
//             tiles back and eat the ceil(L/2) pearls the dead enemy drops.
class Policy {
  public:
    int depthReached() const { return depthReached_; }

    // `deadline` bounds this decision's search, `turnDeadline` the whole turn. An extra
    // step is a later free step of this turn's MOVE: it only walks, inside today's vision.
    Policy(World& w, Params const& p, double deadline, double turnDeadline, bool extraStep = false)
        : w_(w), p_(p), deadline_(deadline), turnDeadline_(turnDeadline), extraStep_(extraStep) {
        gammaPow_.resize(kPowSize);
        gammaPow_[0] = 1.0;
        for (int i = 1; i < kPowSize; i++) gammaPow_[i] = gammaPow_[i - 1] * p_.gamma;
        farPow_.resize(kPowSize);
        farPow_[0] = 1.0;
        for (int i = 1; i < kPowSize; i++) farPow_[i] = farPow_[i - 1] * p_.gammaFar;
        regionPow_.resize(kPowSize);
        regionPow_[0] = 1.0;
        for (int i = 1; i < kPowSize; i++) regionPow_[i] = regionPow_[i - 1] * p_.regionGamma;
    }

    Choice decide() {
        Board const& b = w_.board;
        L_ = w_.t.length;
        queen_ = w_.isQueen();
        grower_ = isGrower(w_.init.id, L_);
        feedHead_ = -1;
        late_ = w_.t.round >= p_.tiebreakRound;
        anchorId_ = w_.anchorId(p_);
        anchor_ = late_ && anchorId_ == w_.init.id;
        if (anchor_) grower_ = true;  // the anchor plays safe: no trades, queen-level caution
        alarm_ = false;
        if (queen_) {
            int close = 0;
            for (World::Seen const& s : w_.others)
                if (isEnemy(s) && b.cheb(s.head, w_.head) <= p_.queenAlarmRadius) close++;
            alarm_ = close >= 2;  // Phase 2: two or more enemy heads close, flee
        }
        // A fresh child's setup can eat most of its first turn late in the game:
        // then play a lean one-step turn.
        lean_ = !extraStep_ && clockNow() > turnDeadline_ - p_.leanMargin;
        buildBase();
        buildTargets();
        if (!lean_) buildFriendFields();
        else noFriendFields();
        buildSquadTargets();
        buildQueenInfo();
        if (!extraStep_) maybeStartExplore();
        updateRegionTarget(!extraStep_);

        // End-game feeding (see Params::feedRound). Small dragons feed the lowest-id
        // teammate they can see with an id below their own. Our queen has the team's
        // lowest id, so it is fed whenever it is in view; the queen itself never feeds,
        // and two dragons never try to feed each other.
        // Phase 1: only the anchor is ever fed, only while it is in view, and only while
        // feeding can still change the tiebreak (anchor not already ahead of the rival by
        // more than feedLead). vD fed whoever had a lower id, even after our queen was dead.
        World::Seen const* fed = nullptr;
        if (w_.t.round >= p_.feedRound && w_.t.round < p_.feedStop && L_ <= p_.feedMaxLen && !anchor_ &&
            !w_.isQueen() && w_.anchorLen(p_) <= w_.rivalLen(p_) + p_.feedLead) {
            for (World::Seen const& s : w_.others)
                if (!isEnemy(s) && s.id == anchorId_) fed = &s;
            if (fed) {
                // Die a few tiles ahead of where it faces, never beside its head: feeders
                // parked on the tiles around the queen's head were boxing her in.
                feedFor_ = fed->head;
                int spot = fed->head;
                for (int i = 0; i < p_.feedAhead && spot >= 0; i++) spot = b.nb[spot * 4 + fed->headDir];
                bool enemyNear = false;
                for (World::Seen const& s : w_.others)
                    if (isEnemy(s) && spot >= 0 && b.cheb(s.head, spot) <= p_.feedEnemyDist) enemyNear = true;
                if (spot >= 0 && !enemyNear && w_.occ[spot] < 0 && !ownCell(spot) && amFeeder(spot)) feedHead_ = spot;
            }
        }
        if (feedHead_ >= 0) {
            grower_ = false;
            hunts_.clear();
            escortOf_ = -1;
            bool there = w_.head == feedHead_ ||
                         (b.cheb(w_.head, feedHead_) <= p_.feedDist && b.cheb(w_.head, feedFor_) >= 2);
            if (!extraStep_ && there && L_ >= 2) {
                // Step into our own neck: we die here and the pearls land by its head.
                Choice c;
                c.dir = w_.t.dir ^ 2;
                c.dest = b.nb[w_.head * 4 + c.dir];
                c.why = "feed";
                c.score = 1e9;
                return c;
            }
        }

        // Depth 1 is the plain one-step evaluation; then deepen while the CPU budget lasts.
        std::vector<Choice> first(4);
        std::vector<std::vector<int>> firstBody(4);
        std::vector<int> none;
        for (int d = 0; d < 4; d++) first[d] = scoreFrom(w_.body, L_, d, 0, none, &firstBody[d]);
        std::vector<double> total(4);
        for (int d = 0; d < 4; d++) total[d] = first[d].score;
        depthReached_ = 1;
        for (int depth = 2; depth <= p_.maxDepth && !lean_ && !timeUp(); depth++) {
            std::vector<double> t(4, -1e18);
            bool complete = true;
            for (int d = 0; d < 4 && complete; d++) {
                Choice const& c = first[d];
                if (c.dest == -1) continue;
                if (c.terminal) { t[d] = c.score; continue; }
                std::vector<int> eaten;
                if (c.eat) eaten.push_back(c.dest);
                double rest = searchFrom(firstBody[d], c.newL, depth - 1, 1, eaten);
                if (timedOut_) complete = false;
                t[d] = rest <= -1e17 ? -900.0 : c.stepTerm + rest;
            }
            if (!complete) break;
            total = t;
            depthReached_ = depth;
        }
        Choice best;
        double bestKey = -1e18;
        for (int d = 0; d < 4; d++) {
            if (first[d].dest == -1) continue;
            Choice c = first[d];
            c.score = total[d];
            // Ties: keep the heading, then a per-dragon order. A strict comparison alone
            // always broke ties toward North, which turned flat areas into the same loop.
            double key = c.score + (d == w_.t.dir ? 1e-3 : 0.0) + 1e-4 * ((d + w_.init.id) % 4);
            if (key > bestKey) best = c, bestKey = key;
        }
        if (best.dest == -1) {
            // Nothing legal: first try a tile we only gave up as a teammate's last exit,
            // otherwise any well-formed move beats the default suicide.
            best.dir = w_.t.dir;
            best.dest = b.nb[w_.head * 4 + best.dir];
            best.why = "trapped";
            // Doomed: die alone. Prefer an enemy head (trade), then kelp / our own body /
            // a teammate's body (only we die); a teammate's head would take it with us.
            int bestRank = 99;
            for (int d = 0; d < 4; d++) {
                int n = b.nb[w_.head * 4 + d];
                int hid = n >= 0 ? w_.occHeadId[n] : -1;
                bool enemyHead = false, friendHead = false;
                for (World::Seen const& s2 : w_.others)
                    if (s2.id == hid) (isEnemy(s2) ? enemyHead : friendHead) = true;
                int rank = enemyHead ? 0 : friendHead ? 9 : 5;
                if (rank < bestRank) {
                    bestRank = rank;
                    best.dir = d;
                    best.dest = n;
                }
            }
            for (int d = 0; d < 4; d++) {
                int n = b.nb[w_.head * 4 + d];
                if (n < 0 || w_.occ[n] >= 0 || base_[n] < INF || ownCell(n)) continue;
                best.dir = d;
                best.dest = n;
                best.why = "shared-exit";
                break;
            }
            if (best.why == "trapped") {
#ifdef BC_DEBUG
            for (int d = 0; d < 4; d++) {
                int n = b.nb[w_.head * 4 + d];
                char const* r = n < 0 ? "kelp" : n == b.nb[w_.head * 4 + (w_.t.dir ^ 2)] ? "neck"
                              : w_.occ[n] >= 0 ? "dragon" : base_[n] >= INF ? "exit" : "own";
                best.why += std::string(" ") + DCH[d] + ":" + r;
                if (n >= 0 && w_.occ[n] >= 0) best.why += std::to_string(w_.occ[n]);
            }
#endif
            }
        }

        // A later free step only walks: splits and sprints happen on a turn's first step.
        if (extraStep_) return best;

        Choice split;
        if (trySplit(split, best)) return split;

        // The queen never sprint-trades: its only job is to stay alive.
        if (p_.sprintTrades && !queen_ && !anchor_ && best.why != "trade" && best.why != "defend" && !lean_) {
            std::string path;
            if (sprintTrade(path)) {
                Choice s;
                s.dir = dirFromChar(path[0]);
                s.dest = -1;  // we die with the target: no body to track
                s.sprint = path;
                s.why = "sprint-trade";
                return s;
            }
        }
        // Boxed in: splitting keeps the front half still this turn while the rear half
        // (a new dragon that moves right away) walks off and frees room.
        // The queen only as a true last resort (queenReverse): a 2-long queen beats a dead one.
        if (best.score < -500 && L_ >= 4 && (!queen_ || p_.queenReverse) && w_.t.units < w_.init.unitLimit) {
            // Reverse: keep a 2-long stub here, the child (our old tail, facing out)
            // leaves with the rest.
            split.split = true;
            split.n = L_ - 2;
            split.why = "reverse";
            return split;
        }
        return best;
    }

  private:
    struct Target {
        int cell;
        double belief;
        int countdown;  // rounds until the bed spawns, -1 none
        double explore;
    };
    enum class Job { None, Attack, Support };
    struct Hunt {
        World::Seen const* enemy;
        double gain;     // length we expect to come out ahead by
        Job job;
        bool threat;     // it is closing in on one of our growers
    };

    static constexpr int kPowSize = 256;
    std::vector<double> gammaPow_;
    double gp(int k) const { return k < 0 ? 1.0 : k >= kPowSize ? 0.0 : gammaPow_[k]; }
    std::vector<double> farPow_;
    double fp(int k) const { return k < 0 ? 1.0 : k >= kPowSize ? 0.0 : farPow_[k]; }
    std::vector<double> regionPow_;
    double rp(int k) const { return k < 0 ? 1.0 : k >= kPowSize ? 0.0 : regionPow_[k]; }
    struct Hot { int cell; double rate; };
    std::vector<Hot> hot_;

    World& w_;
    Params const& p_;
    double deadline_ = 1e9;         // seconds on the turn clock: this decision's search
    double turnDeadline_ = 1e9;     // the whole turn
    bool extraStep_ = false;        // a later free step of this turn's MOVE
    bool queen_ = false;            // we are our team's queen: survive, nothing else
    bool timedOut_ = false;
    int depthReached_ = 0;
    std::vector<int> blkScratch_;
    std::vector<double> belief_;    // per tile, for lookahead pearl pickup
    std::vector<int> countdown_;

    bool lean_ = false;

    void noFriendFields() {
        Board const& b = w_.board;
        friendDist_.assign(b.NC, INF);
        friendId_.assign(b.NC, -1);
        enemyDist_.assign(b.NC, INF);
        friends_.clear();
        enemies_.clear();
        std::vector<int> blk = ownBlk();
        nav_.bfs(b, w_.head, blk, p_.horizon);
        myDist_ = nav_.dist;
    }

    bool timeUp() {
        if (!timedOut_ && clockNow() >= deadline_) timedOut_ = true;
        return timedOut_;
    }
    Nav nav_;
    int L_ = 2;
    bool grower_ = false;
    std::vector<int> base_;       // other dragons' segments = INF, plus own stray segments
    std::vector<Target> targets_;
    std::vector<int> friendDist_; // min distance from any visible teammate head
    std::vector<int> friendId_;
    std::vector<int> enemyDist_;
    struct FriendField { int id; bool grower; int head; std::vector<int> dist; };
    std::vector<FriendField> friends_;
    struct EnemyField { int id; int head; int visible; std::vector<int> dist; };
    std::vector<EnemyField> enemies_;  // the nearest visible enemy heads, with their BFS fields
    std::vector<int> myDist_;     // from our head as it is now
    std::vector<Hunt> hunts_;
    int escortOf_ = -1;           // head tile of the grower we escort, -1 none
    int feedHead_ = -1;           // tile we walk to and die on to feed a lower-id teammate, -1 none
    int feedFor_ = -1;            // head of the teammate we feed
    bool late_ = false;           // round >= tiebreakRound
    int anchorId_ = -1;           // the dragon the team grows for the tiebreak
    bool anchor_ = false;         // late, and we are the anchor
    bool alarm_ = false;          // we are the queen and 2+ enemy heads are within queenAlarmRadius
    bool forceRetarget_ = false;  // looping: choose a different region this turn
    double regionPull_ = 0;       // this turn's pull toward the target region (0: none)
    std::vector<int> fromHead_, queue_;
    int escortRing_ = 0;          // ring we hold around escortOf_
    // our queen, seen from a teammate
    int queenHead_ = -1;          // her head if visible, -1 otherwise
    int queenNeed_ = 0;           // room she needs (same rule as our own `need`)
    int queenRoomBefore_ = -1;    // her room before our move, -1 not checked
    bool defending_ = false;      // we hunt an enemy that threatens one of our growers
    Nav queenNav_;

    bool ownCell(int c) const {
        for (int x : w_.body)
            if (x == c) return true;
        for (int x : w_.ownExtra)
            if (x == c) return true;
        return false;
    }

    bool isEnemy(World::Seen const& s) const { return s.team != w_.init.team; }
    // Everyone expands until the army is big (or late); only then do the starting
    // dragons and long ones switch to growing for the length tiebreak.
    bool isGrower(int id, int len) const {
        bool growPhase = w_.t.units >= p_.growerMinUnits || w_.t.round >= p_.growRound;
        return growPhase && (w_.isInitial(id) || len >= p_.promoteLen);
    }
    // Head-on trades are one-for-one: worth it while our army is not tiny and we do
    // not give up much more length than we take.
    // Phase 4: the opening is for pearls and dragon count.
    bool opening() const { return w_.t.round < p_.openingEnd; }
    bool tradeOk(int myLen, int enemyLen) const {
        if (w_.t.units < p_.tradeMinUnits) return false;
        // A head-on kills both; it only pays when the enemy loses clearly more. In the opening
        // no even trades at all: early segments compound (vD lost 40-49% of its dragons head-on).
        if (opening()) return enemyLen >= myLen + p_.openingTradeMargin;
        // Phase 6: against a trader, no even trades at any time (they win those by numbers).
        if (w_.styleTrader) return enemyLen >= myLen + p_.tradeHeavyMargin;
        return myLen <= enemyLen + p_.tradeSlack;
    }
    bool survival() const { return w_.t.units <= p_.survivalUnits; }

    // Whoever has more heads around a trade site eats most of the pearls the two dead
    // dragons drop. Counts heads near `site`, leaving out ourselves and the enemy we
    // would trade with (`skip`, -1 none).
    bool localOk(int site, int skip) const {
        Board const& b = w_.board;
        int mine = 0, theirs = 0;
        for (World::Seen const& s : w_.others) {
            if (s.id == skip || b.cheb(s.head, site) > p_.localRadius) continue;
            (isEnemy(s) ? theirs : mine)++;
        }
        return mine >= theirs;
    }
    // How far an enemy head can move in one turn to trade with us: its ceil(L/4) free
    // steps plus every segment it can pay (maxSteps).
    int reachOf(int visible) const { return std::min(std::max(maxSteps(visible), 1), p_.reachCap); }
    bool midGame() const { return w_.t.round >= p_.earlyEnd; }
    bool lateGame() const { return w_.t.round >= p_.midEnd; }

    std::vector<int> ownBlk() const {
        std::vector<int> blk = base_;
        markBody(blk, w_.body, L_);
        return blk;
    }

    // Distance from a precomputed field to any tile next to `head` (the head itself is blocked).
    int distToHead(std::vector<int> const& dist, int head) const {
        Board const& b = w_.board;
        int best = INF;
        for (int k = 0; k < 4; k++) {
            int n = b.nb[head * 4 + k];
            if (n >= 0) best = std::min(best, dist[n]);
        }
        return best;
    }

    void buildBase() {
        Board const& b = w_.board;
        base_.assign(b.NC, 0);
        for (int c = 0; c < b.NC; c++)
            if (w_.occ[c] >= 0) base_[c] = INF;
        for (int c : w_.ownExtra) base_[c] = INF;
        timeOtherBodies();

        // Never take a teammate's last way out.
        std::vector<int> blk = base_;
        markBody(blk, w_.body, L_);
        for (World::Seen const& s : w_.others) {
            if (isEnemy(s)) continue;
            int exits = 0, exit = -1;
            for (int d = 0; d < 4; d++) {
                int n = b.nb[s.head * 4 + d];
                if (n >= 0 && blk[n] <= 1) exits++, exit = n;
            }
            if (exits == 1) base_[exit] = INF;
        }
    }

    // Other dragons move too: a crowd treated as permanent walls made every move look
    // cramped. For a dragon whose whole body is in view, segment i (head = 0) of its L
    // segments has left its tile after L - i moves; we add one move of margin (it may
    // act after us this round, or eat). Each body segment faces the next one toward
    // the head, so the body is walked back from the head. The tail is only trusted
    // when every side of it is kelp or a visible tile (nothing hidden could continue it).
    // Anything else stays a wall (INF).
    void timeOtherBodies() {
        Board const& b = w_.board;
        std::vector<int> pointedBy(b.NC, -1);
        for (Part const& part : w_.t.parts) {
            if (part.id == w_.init.id || part.head) continue;
            int c = b.id(part.x, part.y);
            int to = b.nb[c * 4 + part.facing];
            if (to >= 0 && w_.occ[to] == part.id) pointedBy[to] = c;
        }
        std::vector<int> chain;
        for (World::Seen const& s : w_.others) {
            chain.clear();
            for (int c = s.head; c >= 0 && static_cast<int>(chain.size()) < s.visible; c = pointedBy[c])
                chain.push_back(c);
            if (static_cast<int>(chain.size()) != s.visible || s.visible < 2) continue;
            int tail = chain.back();
            bool sealed = true;
            for (int d = 0; d < 4 && sealed; d++) {
                if (b.side(tail, d).kind == 1) continue;
                int n = b.nb[tail * 4 + d];
                sealed = n >= 0 && w_.visible(n);
            }
            if (!sealed) continue;
            int L = static_cast<int>(chain.size());
            for (int i = 0; i < L; i++) base_[chain[i]] = L - i + 2;
        }
    }

    void buildTargets() {
        Board const& b = w_.board;
        targets_.clear();
        belief_.assign(b.NC, 0.0);
        countdown_.assign(b.NC, -1);
        for (int c = 0; c < b.NC; c++) {
            double bel = w_.belief(c, p_);
            int cd = (b.bed[c] == 1 && w_.next[c] >= 0 && w_.next[c] < p_.horizon) ? w_.next[c] : -1;
            belief_[c] = bel;
            countdown_[c] = cd;
            // Never seen: full explore value. Not seen for a while: a smaller value, so an
            // area we searched long ago pulls us back instead of the map going flat.
            double ex = w_.seenRound[c] < 0 ? p_.exploreValue
                      : w_.t.round - w_.seenRound[c] >= p_.staleAge ? p_.staleValue : 0.0;
            if (bel > 0.02 || cd >= 0 || ex > 0) targets_.push_back({c, bel, cd, ex});
        }
        hot_.clear();
        for (int c = 0; c < b.NC; c++) {
            if (b.bed[c] != 1 || b.gapMax[c] <= 0) continue;
            double rate = 2.0 / (b.gapMin[c] + b.gapMax[c]);
            if (rate >= p_.hotRate) hot_.push_back({c, rate});
        }
    }

    void buildFriendFields() {
        Board const& b = w_.board;
        friendDist_.assign(b.NC, INF);
        friendId_.assign(b.NC, -1);
        enemyDist_.assign(b.NC, INF);
        friends_.clear();
        enemies_.clear();
        std::vector<int> blk = ownBlk();
        // Only the nearest heads matter; this bounds CPU when 60+ dragons crowd the vision.
        std::vector<World::Seen const*> near;
        for (World::Seen const& s : w_.others) near.push_back(&s);
        std::sort(near.begin(), near.end(), [&](World::Seen const* x, World::Seen const* y) {
            return b.cheb(x->head, w_.head) < b.cheb(y->head, w_.head);
        });
        if (static_cast<int>(near.size()) > p_.maxRivalFields) near.resize(p_.maxRivalFields);
        for (World::Seen const* sp : near) {
            World::Seen const& s = *sp;
            nav_.bfs(b, s.head, blk, p_.horizon);
            if (isEnemy(s)) {
                for (int c = 0; c < b.NC; c++) enemyDist_[c] = std::min(enemyDist_[c], nav_.dist[c]);
                enemies_.push_back({s.id, s.head, s.visible, nav_.dist});
                continue;
            }
            for (int c = 0; c < b.NC; c++) {
                int d = nav_.dist[c];
                if (d < friendDist_[c] || (d == friendDist_[c] && d != INF && s.id < friendId_[c])) {
                    friendDist_[c] = d;
                    friendId_[c] = s.id;
                }
            }
            friends_.push_back({s.id, isGrower(s.id, s.visible), s.head, nav_.dist});
        }
        nav_.bfs(b, w_.head, blk, p_.horizon);
        myDist_ = nav_.dist;
    }

    // How many visible swarm teammates are closer than us to `head` (ties by id).
    int swarmRank(int head, int mine) const {
        int rank = 0;
        for (FriendField const& f : friends_) {
            if (f.grower) continue;
            int d = distToHead(f.dist, head);
            if (d < mine || (d == mine && d != INF && f.id < w_.init.id)) rank++;
        }
        return rank;
    }

    void buildSquadTargets() {
        Board const& b = w_.board;
        hunts_.clear();
        escortOf_ = -1;
        if (queen_) return;  // the queen never hunts

        // Enemy heads near one of our visible growers are threats whatever their length.
        // Near our queen they are threats from the first round, and even growers break
        // off to kill them.
        for (World::Seen const& e : w_.others) {
            if (!isEnemy(e)) continue;
            bool threat = false, queenThreat = false;
            double protect = 0;
            for (FriendField const& f : friends_) {
                bool nearQueen = f.id == w_.queenId && b.cheb(f.head, e.head) <= p_.queenThreatRadius;
                if (nearQueen || (f.grower && b.cheb(f.head, e.head) <= p_.escortRadius)) {
                    threat = true;
                    queenThreat |= nearQueen;
                    for (World::Seen const& s : w_.others)
                        if (s.id == f.id) protect = std::max<double>(protect, s.visible);
                }
            }
            if (grower_ && !queenThreat) continue;
            if (opening() && !queenThreat) continue;  // Phase 4: no hunts in the opening but the queen's defence
            double gain = threat ? std::max<double>(protect, e.visible) - L_ : e.visible - L_;
            bool worth = queenThreat || (threat ? e.visible >= 2 : tradeOk(L_, e.visible));
            if (!worth) continue;
            int mine = distToHead(myDist_, e.head);
            if (mine == INF) continue;
            int rank = swarmRank(e.head, mine);
            Job job = rank == 0 ? Job::Attack : rank < p_.squadSize ? Job::Support : Job::None;
            if (job != Job::None) hunts_.push_back({&e, gain, job, threat});
        }
        if (grower_) return;

        // Late game: the escorts guard the anchor, a little further out (Phase 1).
        escortRing_ = p_.escortRing;
        if (hunts_.empty() && late_ && anchorId_ != w_.init.id) {
            for (FriendField const& f : friends_) {
                if (f.id != anchorId_) continue;
                int d = distToHead(myDist_, f.head);
                if (d != INF && swarmRank(f.head, d) < p_.escortCount) {
                    escortOf_ = f.head;
                    escortRing_ = p_.anchorEscortRing;
                }
            }
            if (escortOf_ >= 0) return;
        }
        // Idle escort: stay near the closest visible grower if we are among its first escorts.
        if (hunts_.empty() && midGame()) {
            int bestD = INF;
            for (FriendField const& f : friends_) {
                if (!f.grower) continue;
                int d = distToHead(myDist_, f.head);
                if (d == INF || d >= bestD) continue;
                if (swarmRank(f.head, d) < p_.escortCount) {
                    bestD = d;
                    escortOf_ = f.head;
                }
            }
        }
    }

    void buildQueenInfo() {
        Board const& b = w_.board;
        queenHead_ = -1;
        queenRoomBefore_ = -1;
        defending_ = false;
        for (Hunt const& h : hunts_) defending_ |= h.threat;
        if (queen_) return;
        for (World::Seen const& s : w_.others) {
            if (isEnemy(s) || s.id != w_.queenId) continue;
            queenHead_ = s.head;
            queenNeed_ = std::min(static_cast<int>(p_.spaceFactor * s.visible) + p_.spaceMargin, b.NC / 2);
            if (b.cheb(s.head, w_.head) <= p_.queenBoxRadius + 1) {
                std::vector<int> blk = ownBlk();
                queenRoomBefore_ = queenNav_.flood(b, s.head, blk, queenNeed_ + 1);
            }
        }
    }

    // Looping (our head stood here loopHits times lately): pick the nearest stale or
    // never-seen tile at least 4 moves away and head for it for a while.
    // Looping (our head stood here loopHits times lately): Phase 3 replaces the old
    // single-tile explore target with "commit to a different region" (3d).
    void maybeStartExplore() {
        if (w_.recentCount(w_.head) >= p_.loopHits) forceRetarget_ = true;
    }

    // ---- territory (plan Phase 3) ----------------------------------------------------

    // Value of a region: pearls believed there, known beds (hot beds more), never-seen
    // share, and how long since we last looked.
    double regionValue(int r) const {
        Board const& b = w_.board;
        auto const& ts = w_.regions.tiles[r];
        double pearls = 0, beds = 0;
        int unseen = 0, last = -1;
        for (int c : ts) {
            if (belief_[c] > 0.02) pearls += belief_[c];
            if (b.bed[c] == 1) {
                double rate = b.gapMax[c] > 0 ? 2.0 / (b.gapMin[c] + b.gapMax[c]) : 0.0;
                beds += 1.0 + 10.0 * rate;
            }
            if (w_.seenRound[c] < 0) unseen++;
            else last = std::max(last, w_.seenRound[c]);
        }
        int age = last < 0 ? p_.regionStaleCap : std::min(p_.regionStaleCap, w_.t.round - last);
        return p_.regionPearl * pearls + p_.regionBed * beds +
               p_.regionUnseen * unseen / static_cast<double>(ts.size()) +
               p_.regionStale * age / static_cast<double>(p_.regionStaleCap);
    }

    // Choose the target region: value / (1 + teammates' claims), discounted by terrain path
    // distance. In the opening the k-th lowest-id teammate nearby takes the k-th best one,
    // so the starting dragons spread out instead of clumping (3c).
    void chooseRegion(int exclude) {
        Board const& b = w_.board;
        Regions const& R = w_.regions;
        terrainField(b, std::vector<int>{w_.head}, fromHead_, queue_);
        std::vector<int> rdist(R.count, INF);
        for (int c = 0; c < b.NC; c++)
            if (fromHead_[c] < rdist[R.of[c]]) rdist[R.of[c]] = fromHead_[c];
        std::vector<std::pair<double, int>> cand;
        for (int r = 0; r < R.count; r++) {
            if (r == exclude || rdist[r] == INF || static_cast<int>(R.tiles[r].size()) < p_.regionMinArea) continue;
            double v = regionValue(r) / (1.0 + w_.claimsOn(r, p_.claimMemory)) * rp(rdist[r]);
            cand.push_back({v, r});
        }
        if (cand.empty()) return;
        std::sort(cand.begin(), cand.end(), [](auto const& x, auto const& y) { return x.first > y.first; });
        size_t pick = 0;
        if (w_.t.round < p_.openingSpreadRounds) {
            int rank = 0;
            for (World::Seen const& s : w_.others)
                if (!isEnemy(s) && s.id < w_.init.id && b.cheb(s.head, w_.head) <= 2 * p_.regionSize) rank++;
            pick = std::min(cand.size() - 1, static_cast<size_t>(rank));
        }
        w_.targetRegion = cand[pick].second;
        w_.targetUntil = w_.t.round + p_.regionCommit;
        w_.targetValue0 = std::max(0.05, regionValue(w_.targetRegion));
    }

    // Keep the regions, the target and its path field up to date; set this turn's pull.
    void updateRegionTarget(bool mayChoose) {
        Board const& b = w_.board;
        Regions& R = w_.regions;
        regionPull_ = 0;
        if (w_.corridors.builtFor != b.version) w_.corridors.build(b, p_.corridorMinLen);  // Phase 5
        if (R.builtFor != b.version) {
            R.build(b, p_.regionSize);  // terrain knowledge changed: ids changed too
            w_.targetRegion = -1;
            w_.fieldRegion = -1;
        }
        int here = R.of[w_.head];
        bool hungry = w_.t.round - w_.lastEatRound >= p_.hungryTurns;
        if (mayChoose) {
            int exclude = -1;
            bool again = w_.targetRegion < 0 || w_.t.round > w_.targetUntil;
            if (!again && here == w_.targetRegion && regionValue(here) < p_.regionDone * w_.targetValue0) again = true;
            if (forceRetarget_) again = true, exclude = here;
            if (hungry && w_.t.round >= w_.hungryRetarget) {
                // Orbit breaker (3d): nothing eaten for a while, leave this region for good.
                again = true, exclude = here;
                w_.hungryRetarget = w_.t.round + p_.hungryTurns;
            }
            if (again) chooseRegion(exclude);
        }
        if (w_.targetRegion < 0 || w_.targetRegion >= R.count) return;
        if (w_.fieldRegion != w_.targetRegion || w_.fieldVersion != b.version) {
            terrainField(b, R.tiles[w_.targetRegion], w_.regionField, queue_);
            w_.fieldRegion = w_.targetRegion;
            w_.fieldVersion = b.version;
        }
        if (here != w_.targetRegion) regionPull_ = p_.wRegion * (hungry ? p_.hungryBoost : 1.0);
    }

    // One feeder at a time: the visible small teammate closest to the spot (lowest id on
    // ties) feeds; everyone else carries on.
    bool amFeeder(int spot) const {
        int mine = myDist_[spot];
        if (mine == INF) return false;
        for (FriendField const& f : friends_) {
            if (f.id == w_.queenId || f.head == feedFor_) continue;
            int len = 0;
            for (World::Seen const& s : w_.others)
                if (s.id == f.id) len = s.visible;
            if (len > p_.feedMaxLen) continue;
            int d = f.dist[spot];
            if (d < mine || (d == mine && f.id < w_.init.id)) return false;
        }
        return true;
    }

    // Value of stepping into an unknown portal, or false if we should not. A bad report
    // keeps everyone out, a good one lets anyone in; otherwise only one scout goes: no
    // lower-id non-queen teammate may be nearby (it scouts instead).
    bool blindPortalValue(int pid, int L, double& v) const {
        Board const& b = w_.board;
        double reported = pid >= 0 ? w_.portalScore(pid, p_.reportWait) : 0.0;
        if (reported < 0) return false;
        if (reported > 0) {
            v = p_.wPortalReport * reported;
            return true;
        }
        for (World::Seen const& s : w_.others)
            if (!isEnemy(s) && s.id != w_.queenId && s.id < w_.init.id && b.cheb(s.head, w_.head) <= p_.scoutRadius)
                return false;
        v = p_.wScout - p_.scoutLenCost * L;
        return v > 0;
    }

    Hunt const* huntAt(int headCell) const {
        for (Hunt const& h : hunts_)
            if (h.enemy->head == headCell) return &h;
        return nullptr;
    }

    bool nextToEnemyHead(int cell, int& enemyLen, bool& isHunt) const {
        Board const& b = w_.board;
        enemyLen = 0;
        isHunt = false;
        bool found = false;
        for (World::Seen const& s : w_.others) {
            if (!isEnemy(s)) continue;
            for (int d = 0; d < 4; d++)
                if (b.nb[s.head * 4 + d] == cell) {
                    found = true;
                    enemyLen = std::max(enemyLen, s.visible);
                    if (huntAt(s.head)) isHunt = true;
                }
        }
        return found;
    }

    // One step from a simulated state: `body` (head first, true length L) after k of
    // our own moves this turn-plan, with `eaten` pearls already taken along the way.
    // k = 0 is the real move; deeper k is lookahead with other dragons held still.
    Choice scoreFrom(std::vector<int> const& body, int L, int d, int k, std::vector<int> const& eaten,
                     std::vector<int>* nextBody = nullptr) {
        Board const& b = w_.board;
        Choice c;
        c.dir = d;
        int head = body.front();
        int dest = b.nb[head * 4 + d];
        // A later free step stays on tiles we can see this turn: dragons outside vision
        // are unknown, and so is the far side of a blind portal.
        if (extraStep_ && k == 0 && (dest < 0 || !w_.visible(dest))) return c;
        // The queen never crosses a portal, known or not, and never plans through one.
        // (If a portal is its only way out, decide()'s last-resort fallback still takes it.)
        if (queen_ && b.side(head, d).kind == 2) {
            // Phase 2: only a known portal a teammate reported as good (flee through safe space).
            int pid = b.side(head, d).pid;
            if (dest < 0 || pid < 0 || w_.portalScore(pid, p_.reportWait) <= 0) return c;
        }
        if (dest < 0) {
            if (b.side(head, d).kind == 2) {
                // Unknown portal: we have not seen the other side, so nothing is searched
                // past it. A teammate's report decides; with none, one scout goes.
                double v = 0;
                if (!blindPortalValue(b.side(head, d).pid, L, v)) return c;
                c.dest = -2;
                c.score = v;
                c.why = "scout";
                c.terminal = true;
                return c;
            }
            return c;  // kelp or wall
        }
        for (int x : body)
            if (x == dest) return c;  // own segment, tail included
        if (w_.occ[dest] < 0 && base_[dest] >= INF) return c;  // own stray segment or a teammate's last exit

        if (w_.occ[dest] >= 0) {
            if (k > 0) return c;  // lookahead treats other dragons as walls
            // Stepping onto an enemy head kills both. Swarm does it on squad targets;
            // anyone does it when the trade is clearly good.
            int hid = w_.occHeadId[dest];
            for (World::Seen const& s : w_.others) {
                if (s.id != hid || !isEnemy(s)) continue;
                Hunt const* h = huntAt(s.head);
                double gain = s.visible - L;
                // The queen never trades; growers only trade to defend the queen.
                if (h && !queen_ && (!grower_ || h->threat)) {
                    c.dest = dest;
                    c.score = 100.0 + h->gain;
                    c.why = h->threat ? "defend" : "trade";
                    c.terminal = true;
                } else if (tradeOk(L, s.visible) && !grower_ && !queen_ &&
                           (!w_.styleTrader || localOk(dest, s.id))) {  // Phase 6: vs a trader, only with local numbers
                    c.dest = dest;
                    c.score = 50.0 + gain;
                    c.why = "trade";
                    c.terminal = true;
                }
            }
            return c;
        }

        c.dest = dest;
        bool taken = std::find(eaten.begin(), eaten.end(), dest) != eaten.end();
        if (k == 0) c.eat = w_.seenRound[dest] == w_.t.round && w_.seenPearl[dest];
        else c.eat = !taken && (belief_[dest] >= 0.5 || (countdown_[dest] >= 0 && countdown_[dest] <= k));
        int newL = L + (c.eat ? 1 : 0);

        std::vector<int> local;
        std::vector<int>& nb2 = nextBody ? *nextBody : local;
        nb2.clear();
        nb2.reserve(body.size() + 1);
        nb2.push_back(dest);
        nb2.insert(nb2.end(), body.begin(), body.end());
        if (!c.eat && static_cast<int>(nb2.size()) > newL) nb2.pop_back();
        c.newL = newL;

        std::vector<int>& blk = blkScratch_;
        blk = base_;
        markBody(blk, nb2, newL);

        int need = std::min(static_cast<int>(p_.spaceFactor * newL) + p_.spaceMargin, b.NC / 2);
        int space = nav_.flood(b, dest, blk, need + 1);
        // Below our own length is a real trap: vetoed. Between that and `need` is only
        // tight: a graded penalty, and the pearls there still count (they used to be
        // thrown away, which is why pockets with pearls were never entered).
        int hardNeed = std::min(newL, need);
        // Reverse by splitting: a dragon of 4+ can split off everything but a 2-long stub;
        // the child's head is our tail and faces out. So a dead end (a fountain corridor,
        // a pocket) is fine as long as the tail side has room; it costs the 2-long stub.
        bool viaReverse = false;
        bool splitAllowed = true;
        if (w_.t.units >= w_.init.unitLimit) splitAllowed = false;
        if (w_.t.round >= p_.feedRound) splitAllowed = false;
        if (queen_) splitAllowed = false;  // the queen never plans to enter a pocket and split out
        if (grower_) {
            if (lateGame()) splitAllowed = false;
            int keep = p_.growerKeepBase + w_.t.round / p_.growerKeepEvery;
            if (newL < keep + p_.growerChild) splitAllowed = false;
        } else {
            if (newL < p_.swarmSplitLen) splitAllowed = false;
            if (w_.t.round >= p_.growRound && w_.t.units >= p_.lateSplitUnits) splitAllowed = false;
        }

        if (splitAllowed && space < hardNeed && newL >= 4 && static_cast<int>(body.size()) == newL) {
            int childNeed = std::min(static_cast<int>(p_.spaceFactor * (newL - 2)) + p_.spaceMargin, b.NC / 2);
            std::vector<int> blk2 = base_;
            for (size_t i = 0; i + 1 < body.size(); i++) blk2[body[i]] = INF;
            int tail = body.back();
            int room = 0;
            for (int q = 0; q < 4 && room < childNeed; q++) {
                int n = b.nb[tail * 4 + q];
                if (n >= 0 && blk2[n] <= 1) room = std::max(room, nav_.flood(b, n, blk2, childNeed + 1) + 1);
            }
            if (room >= childNeed) viaReverse = true;
        }

        nav_.bfs(b, dest, blk, p_.horizon);
        std::vector<int> const& dist = nav_.dist;

        double value = 0;
        for (Target const& t : targets_) {
            if (t.cell == dest) continue;
            int dd = dist[t.cell];
            if (dd == INF) continue;
            if (k > 0 && std::find(eaten.begin(), eaten.end(), t.cell) != eaten.end()) continue;
            int m = dd + 1 + k;  // moves from now, counting the ones already planned
            double v = t.belief * gp(m);
            if (t.countdown >= 0 && t.belief < 0.5)
                v = std::max(v, 0.9 * gp(std::max(m, t.countdown + 1)));
            if (v > 0) {
                int fd = friendDist_[t.cell];
                // A closer teammate claims most of it, not all: in a crowd every pearl was
                // "claimed" (often by a dragon stuck circling) and the map went flat.
                if (fd < m || (fd == m && friendId_[t.cell] < w_.init.id))
                    v *= fd <= p_.claimRadius ? p_.claimNear : p_.claimFar;
                else if (enemyDist_[t.cell] < m) v *= p_.enemyCloserFactor;
            }
            v += t.explore * gp(m);
            value += v;
        }

        // Long-range pull toward fountains nobody visible is closer to.
        for (Hot const& h : hot_) {
            int dd = dist[h.cell];
            if (dd == INF) {
                // beyond the BFS horizon: no pull (keeps CPU bounded)
                continue;
            }
            int m = dd + 1 + k;
            // A fountain cluster feeds several dragons; allow congregating to hoard the area.
            int olderFriendsNear = 0;
            for (FriendField const& f : friends_) {
                if (f.dist[h.cell] <= p_.hotYield && f.id < w_.init.id) {
                    olderFriendsNear++;
                }
            }
            int capacity = std::max(1, static_cast<int>(h.rate * 5.0));

            double friendFactor = 1.0;
            if (olderFriendsNear >= capacity) {
                friendFactor = 0.05; // Hotspot is mathematically full of older snakes! We must yield!
            } else if (friendDist_[h.cell] < m && friendDist_[h.cell] <= p_.hotYield) {
                if (friendId_[h.cell] > w_.init.id) {
                    friendFactor = 0.1; // Yield to higher ID snakes just in case
                } else {
                    friendFactor = 0.8; // High ID snakes take priority but don't crowd 100%
                }
            }
            value += p_.wHot * h.rate * friendFactor * fp(m);
        }

        std::string why;
        // Explore mode (we were looping): a long-range pull toward one stale tile.
        if (w_.exploreTarget >= 0 && dist[w_.exploreTarget] != INF) {
            value += p_.wExploreTarget * fp(dist[w_.exploreTarget] + k);
            why = "explore";
        }
        // Phase 6: against a trader, swarm dragons keep a partner about pairRing away, so the
        // pearls a trade drops are ours to eat.
        if (p_.wPair > 0 && !queen_ && !grower_ && feedHead_ < 0) {
            int bestD = INF;
            for (FriendField const& f : friends_)
                if (f.id != w_.queenId && f.dist[dest] < bestD) bestD = f.dist[dest];
            if (bestD <= p_.pairMaxDist) value += p_.wPair * gp(std::abs(bestD + k - p_.pairRing));
        }
        // Territory (Phase 3): pull toward the target region along the terrain path field.
        // It follows gaps and known portals, so routes to another zone go via its gateways.
        if (regionPull_ > 0 && w_.fieldRegion == w_.targetRegion && !w_.regionField.empty()) {
            int dd = w_.regionField[dest];
            if (dd != INF) {
                value += regionPull_ * rp(dd + k);
                if (why.empty()) why = "region";
            }
        }
        for (Hunt const& h : hunts_) {
            int dd = distToHead(dist, h.enemy->head);
            if (dd == INF) continue;
            if (h.job == Job::Attack) {
                // Aim at the head and at the tile it is facing into.
                int ahead = b.nb[h.enemy->head * 4 + h.enemy->headDir];
                if (ahead >= 0 && dist[ahead] != INF) dd = std::min(dd, dist[ahead]);
                value += p_.wHunt * (1.0 + h.gain / 4.0) * gp(dd + k);
                why = h.threat ? "intercept" : "hunt";
            } else {
                value += p_.wSupport * gp(std::abs(dd + k - p_.supportRing));
                if (why.empty()) why = "support";
            }
        }
        if (feedHead_ >= 0) {
            int dd = dist[feedHead_];
            if (dd != INF) value += p_.wFeed * gp(dd + k);
            why = "to-feed";
        }
        if (escortOf_ >= 0) {
            int dd = distToHead(dist, escortOf_);
            if (dd != INF) value += p_.wEscort * gp(std::abs(dd + k - escortRing_));
            if (why.empty()) why = "escort";
        }

        double danger = 0;
        int enemyLen = 0;
        bool huntNext = false;
        double mult = (queen_ || anchor_) ? p_.queenDanger : grower_ ? p_.growerDanger : survival() ? p_.survivalDanger : 1.0;
        if (lateGame()) mult *= 2.0;
        if (nextToEnemyHead(dest, enemyLen, huntNext)) {
            // Parking next to an enemy head hands it the choice (and the drops). Only a
            // trade we would take anyway, with the local numbers, makes that acceptable.
            // Growers only want it to defend the queen (their only hunts); the queen never.
            bool wanted = !queen_ && (huntNext || (!grower_ && tradeOk(newL, enemyLen)));
            double favour = 1.0;
            if (p_.exposureMode == 0) favour = wanted ? 0.0 : 1.0;
            else if (p_.exposureMode == 1) favour = wanted && localOk(dest, -1) ? p_.exposedFavour : 1.0;
            else favour = wanted && localOk(dest, -1) ? 0.0 : 1.0;
            danger = p_.wDanger * newL * mult * favour;
            if (wanted) danger -= p_.wDanger * enemyLen * mult * 3.0; // Strongest kamikaze pull when directly adjacent!
        }
        if (k == 0 && p_.exposureMode != 0) {
            // Sprint reach: an enemy of length Le can MOVE up to maxSteps(Le) steps onto our head.
            for (EnemyField const& e : enemies_) {
                int dd = e.dist[dest];
                if (dd <= 1 || dd > reachOf(e.visible)) continue;
                bool local = !queen_ && localOk(dest, -1);  // the queen takes the full danger
                if (p_.exposureMode == 2 && local) continue;
                bool wanted = !queen_ && (huntAt(e.head) != nullptr || (!grower_ && tradeOk(newL, e.visible)));
                if (wanted) {
                    danger -= p_.wExposed * e.visible * mult * 2.0; // Huge bonus to actively kamikaze!
                } else {
                    double favour = local ? p_.exposedFavour : 1.0;
                    danger += p_.wExposed * newL * mult * favour;
                }
            }
        }
        if (grower_ || queen_) {
            // Keep a buffer: enemy heads two steps away are a problem too.
            double w = queen_ ? p_.queenDanger : p_.growerDanger;
            for (World::Seen const& s : w_.others)
                if (isEnemy(s) && distToHead(dist, s.head) <= 1) danger += p_.wDanger * w;
        }
        if (queen_ && k == 0) {
            // Phase 2: count the enemy heads that can reach this tile this round (their free
            // steps plus what they can pay, capped by reachCap; +1 for the step onto us), and
            // charge extra when several can.
            int reachers = 0;
            for (EnemyField const& e : enemies_)
                if (e.dist[dest] != INF && e.dist[dest] <= reachOf(e.visible) + 1) reachers++;
            danger += p_.wQueenReach * reachers;
            if (reachers >= 2) danger += p_.wQueenMulti * (reachers - 1);
            if (alarm_) {
                // Flee: the further this tile is from the close enemy heads, the better.
                int cap = 2 * p_.queenAlarmRadius;
                double away = 0;
                for (EnemyField const& e : enemies_)
                    if (b.cheb(e.head, w_.head) <= p_.queenAlarmRadius)
                        away += std::min(e.dist[dest] == INF ? cap : e.dist[dest], cap) / static_cast<double>(cap);
                value += p_.wQueenFlee * away;
            }
        }
        if (queen_ && k == 0) {
            // The queen's sonar (World::enemyEcho): steer off directions where a recent ray
            // met an enemy first, and lean toward ones where it met a teammate.
            int age = w_.t.round - w_.enemyEcho[d];
            if (w_.enemyEcho[d] >= 0 && age <= p_.sonarMemory) danger += p_.wSonarEnemy;
            age = w_.t.round - w_.allyEcho[d];
            if (w_.allyEcho[d] >= 0 && age <= p_.sonarMemory) danger -= p_.wSonarAlly;
        }

        if (k == 0) {
            // Anti-loop: stepping back onto tiles we stood on lately costs a little per visit.
            danger += p_.wRevisit * w_.recentCount(dest);
            // Personal space for our queen: teammates keep off her, unless defending her.
            if (!queen_ && queenHead_ >= 0 && !defending_) {
                int ch = b.cheb(dest, queenHead_);
                if (ch <= p_.queenSpaceRadius) danger += p_.wQueenSpace * (p_.queenSpaceRadius + 1 - ch);
                for (int q = 0; q < 4; q++)
                    if (b.nb[queenHead_ * 4 + q] == dest) danger += p_.wQueenAdjacent;  // Phase 2
                if (ch <= p_.queenBoxRadius && queenRoomBefore_ >= 0) {
                    // Would this move shrink the queen's room below what she needs?
                    int after = queenNav_.flood(b, queenHead_, blk, queenNeed_ + 1);
                    if (after < queenNeed_ && after < queenRoomBefore_) danger += p_.wQueenBox;
                }
            }
        }

        if (k == 0) {
            // Phase 5: how deep a dead end this move leads into (one way on, then none), with
            // our own body timed. vD's 2402 wall deaths almost never had a free neighbour: they
            // were dead ends walked into, not misjudged steps.
            int depth = deadEndDepth(b, head, dest, blk, p_.deadEndCap);
            if (depth > 0) danger += p_.wDeadEnd * depth;
            // Phase 5: do not enter a 1-wide corridor a teammate is in or has reserved: two
            // dragons meeting inside one is how most of our crashes into teammates happened.
            Corridors const& C = w_.corridors;
            if (C.builtFor == b.version) {
                int cor = C.of[dest];
                if (cor >= 0 && cor != C.of[head]) {
                    bool busy = w_.reservedByOther(cor, p_.corridorMemory);
                    for (World::Seen const& s : w_.others)
                        if (!isEnemy(s) && C.of[s.head] == cor) busy = true;
                    if (busy) danger += p_.wCorridorBusy;
                }
            }
        }

        // Pockets: a tile whose only other way out is one more tile is where dragons get sealed in.
        int exits = 0;
        for (int q = 0; q < 4; q++) {
            int n = b.nb[dest * 4 + q];
            if (n >= 0 && n != head && blk[n] <= 1) exits++;
        }
        if (exits <= 1 && k == 0) danger += p_.wPocket;  // corridors would pile this up along a plan
        // Through a portal the far side may be out of vision. Only the real first step
        // pays for that (lookahead leaves vision all the time), and only much when we
        // recently saw dragons around the exit.
        if (k == 0 && !w_.visible(dest) && dest != b.id(b.X(head) + DX[d], b.Y(head) + DY[d])) {
            bool busy = false;
            for (int q = -1; q < 4 && !busy; q++) {
                int n = q < 0 ? dest : b.nb[dest * 4 + q];
                busy = n >= 0 && w_.occSeen[n] >= 0 && w_.t.round - w_.occSeen[n] <= p_.blindMemory;
            }
            danger += busy ? p_.wBlind * (1.0 + 0.25 * newL) : p_.wBlindQuiet;
        }
        // Heads parked next to a portal are what dragons coming through it crash into
        // (they cannot see us). Pass through or move on; do not loiter there.
        // Only pacing counts: staying beside a portal without going through it. Walking up
        // to a portal and crossing it is free.
        bool crossing = dest != b.id(b.X(head) + DX[d], b.Y(head) + DY[d]);
        if (k == 0 && b.portalSide[dest] && b.portalSide[head] && !crossing) danger += p_.wPortalLoiter;

        double cramp = space < need ? p_.wCramped * (need - space) / need : 0.0;
        if (crossing) {
            int pid = b.side(head, d).pid;
            if (pid >= 0) danger -= p_.wPortalReport * w_.portalScore(pid, p_.reportWait);
        }
        c.stepTerm = (c.eat ? p_.eatBonus : 0.0) - danger;
        if (viaReverse) c.stepTerm -= p_.wReverse;
        if (k == 0) c.stepTerm -= cramp;  // the real move pays it inside deeper plans too
        if (queen_) value += p_.wQueenRoom * std::min(space, need) / need;  // Phase 2: keep escape room
        c.score = value + c.stepTerm + p_.wSpace * std::min(space, need) / need - (k == 0 ? 0.0 : cramp);
        if (space < hardNeed && !viaReverse) {
            c.score = -1000.0 + space;  // vetoed, kept only as a last resort
            c.terminal = true;
        }
        c.why = space < need ? "cramped" : !why.empty() ? why : (c.eat ? "eat" : "forage");
        return c;
    }

    // Best score reachable from this state within `depth` more moves; NaN-free,
    // returns -1e18 when no move is legal. Sets timedOut_ when the deadline passes.
    double searchFrom(std::vector<int> const& body, int L, int depth, int k, std::vector<int>& eaten) {
        double best = -1e18;
        std::vector<int> next;
        for (int d = 0; d < 4; d++) {
            if (timeUp()) return best;
            Choice c = scoreFrom(body, L, d, k, eaten, &next);
            if (c.dest == -1) continue;
            double v = c.score;
            if (depth > 1 && !c.terminal) {
                if (c.eat) eaten.push_back(c.dest);
                std::vector<int> child = next;
                double rest = searchFrom(child, c.newL, depth - 1, k + 1, eaten);
                if (c.eat) eaten.pop_back();
                // A dead end deeper down is as bad as it looks; otherwise add what this step earned.
                v = rest <= -1e17 ? -900.0 : c.stepTerm * gp(k) + rest;
            }
            best = std::max(best, v);
        }
        return best;
    }

    // Army cap scaled to the map: past it, extra dragons only crowd each other.
    int unitCap() const {
        int cap = std::max(p_.minUnitCap, w_.board.NC / p_.unitsPerTiles);
        return std::min(cap, w_.init.unitLimit);
    }

    // A split child is born at our tail. Too close to the queen or a grower it boxes them in.
    bool tooCloseToQueen(int cell) const {
        Board const& b = w_.board;
        for (World::Seen const& s : w_.others) {
            if (isEnemy(s)) continue;
            if (s.id == w_.queenId && b.cheb(s.head, cell) <= p_.splitQueenDist) return true;
        }
        for (FriendField const& f : friends_)
            if (f.grower && b.cheb(f.head, cell) <= p_.splitQueenDist) return true;
        return false;
    }

    // The queen builds the first army on maps where she starts alone, then stops: only
    // early (queenSplitUntil), only when long enough, never next to teammates (her child
    // would be born into a crowd), never with an enemy near, both halves roomy.
    bool queenSplit(Choice& out) {
        Board const& b = w_.board;
        if (w_.t.round >= p_.queenSplitUntil || L_ < p_.queenSplitMinLen) return false;
        if (w_.t.units >= unitCap()) return false;
        for (World::Seen const& s : w_.others) {
            int r = isEnemy(s) ? p_.splitEnemyDist : p_.queenCrowdRadius;
            if (b.cheb(s.head, w_.head) <= r) return false;
        }
        int n = L_ / 2, keep = L_ - n;
        if (keep < p_.queenKeepLen) n = L_ - p_.queenKeepLen, keep = p_.queenKeepLen;  // Phase 2
        if (n < 2) return false;
        std::vector<int> parent(w_.body.begin(), w_.body.begin() + keep);
        std::vector<int> child(w_.body.rbegin(), w_.body.rbegin() + n);
        std::vector<int> blk = base_;
        for (int c : child) blk[c] = INF;
        markBody(blk, parent, keep);
        if (!hasRoomyMove(parent.front(), blk, keep)) return false;
        blk = base_;
        for (int c : parent) blk[c] = INF;
        markBody(blk, child, n);
        if (!hasRoomyMove(child.front(), blk, n)) return false;
        out.split = true;
        out.n = n;
        out.why = "queen-split";
        return true;
    }

    // Phase 4: split pacing by economy. Two foragers need food: we must have eaten recently,
    // and there must be at least two regions within reach worth foraging (one for each half).
    // Lenient on purpose: every rule that cut splitting hard lost to vD (0-1 of 16).
    bool economyAllowsSplit() {
        if (w_.t.round - w_.lastEatRound >= p_.hungryTurns) return false;
        Board const& b = w_.board;
        Regions const& R = w_.regions;
        if (R.count == 0 || R.builtFor != b.version) return true;  // no region data yet: do not block
        terrainField(b, std::vector<int>{w_.head}, fromHead_, queue_);
        std::vector<int> rdist(R.count, INF);
        for (int c = 0; c < b.NC; c++)
            if (fromHead_[c] < rdist[R.of[c]]) rdist[R.of[c]] = fromHead_[c];
        int good = 0;
        for (int r = 0; r < R.count && good < 2; r++) {
            if (rdist[r] > p_.splitRegionDist || static_cast<int>(R.tiles[r].size()) < p_.regionMinArea) continue;
            if (regionValue(r) / (1.0 + w_.claimsOn(r, p_.claimMemory)) >= p_.splitRegionValue) good++;
        }
        return good >= 2;
    }

    bool trySplit(Choice& out, Choice const& bestMove) {
        Board const& b = w_.board;
        if (late_) return false;  // Phase 1: from tiebreakRound length is kept, not divided
        if (w_.t.units >= w_.init.unitLimit || !w_.bodyKnown()) return false;
        if (queen_) return queenSplit(out);  // the queen has her own, much stricter rule
        if (tooCloseToQueen(w_.body.back())) return false;

        // Tactical Split: If an enemy is within sprint range, split to save mass!
        // We keep just enough length to sprint to them: the shortest L with maxSteps(L) >= distance.
        int minEnemyD = INF;
        for (EnemyField const& e : enemies_) {
            if (queen_) break;  // the queen never splits to fight
            // Only split for enemies that are actually a threat or worth trading with!
            // Don't shatter a huge dragon just to assassinate a tiny length-2 snake.
            if (e.visible < L_ - p_.tacticalSplitSlack && e.visible < p_.tacticalSplitMinThreat) continue;
            int D = e.dist[w_.head];
            if (D < minEnemyD) minEnemyD = D;
        }

        if (minEnemyD <= p_.sprintMax + 1) {
            int neededLen = 2;
            while (maxSteps(neededLen) < minEnemyD) neededLen++;
            int splitN = L_ - neededLen;
            if (splitN >= 2) {
                std::vector<int> parent(w_.body.begin(), w_.body.begin() + neededLen);
                std::vector<int> child(w_.body.rbegin(), w_.body.rbegin() + splitN);

                std::vector<int> blk = base_;
                for (int c : child) blk[c] = INF;
                markBody(blk, parent, neededLen);
                bool parentRoomy = hasRoomyMove(parent.front(), blk, neededLen);

                blk = base_;
                for (int c : parent) blk[c] = INF;
                markBody(blk, child, splitN);
                bool childRoomy = hasRoomyMove(child.front(), blk, splitN);

                if (parentRoomy && childRoomy) {
                    out.split = true;
                    out.n = splitN;
                    out.why = "tactical-split";
                    return true;
                }
            }
        }

        if (bestMove.eat || bestMove.why == "trade" || bestMove.why == "defend") return false;
        for (Hunt const& h : hunts_)
            if (h.job == Job::Attack) return false;  // attackers stay whole and committed

        int n = 0;
        if (w_.t.round >= p_.feedRound) return false;  // feeding phase: consolidate, never split
        if (w_.t.units >= unitCap()) return false;     // enough dragons for this map
        if (grower_) {
            if (lateGame()) return false;  // the longest dragon decides the tiebreak
            int keep = p_.growerKeepBase + w_.t.round / p_.growerKeepEvery;
            if (L_ < keep + p_.growerChild) return false;
            n = p_.growerChild;
        } else {
            if (L_ < (midGame() ? p_.swarmSplitLen : p_.swarmSplitLenEarly)) return false;
            // Late game: the tiebreak is the longest dragon, so stop splitting and let
            // length pile up, unless the army needs rebuilding.
            if (w_.t.round >= p_.growRound && w_.t.units >= p_.lateSplitUnits) return false;
            n = L_ / 2;
        }
        for (World::Seen const& s : w_.others)
            if (isEnemy(s) && b.cheb(s.head, w_.head) <= p_.splitEnemyDist) return false;
        if (!economyAllowsSplit()) return false;  // Phase 4

        int keep = L_ - n;
        std::vector<int> parent(w_.body.begin(), w_.body.begin() + keep);
        std::vector<int> child(w_.body.rbegin(), w_.body.rbegin() + n);

        // Parent must still have a roomy move with the child as a wall, and vice versa.
        std::vector<int> blk = base_;
        for (int c : child) blk[c] = INF;
        markBody(blk, parent, keep);
        if (!hasRoomyMove(parent.front(), blk, keep)) return false;

        blk = base_;
        for (int c : parent) blk[c] = INF;
        markBody(blk, child, n);
        if (!hasRoomyMove(child.front(), blk, n)) return false;

        out.split = true;
        out.n = n;
        out.why = grower_ ? "bud" : "split";
        return true;
    }

    // A sprint trade: MOVE 2..sprintMax steps through free tiles onto an enemy head we are
    // allowed to trade with, where we have the local numbers to eat the drops. We die on
    // arrival, so paid steps cost nothing: a length-L dragon can go maxSteps(L).
    // Picks the longest such enemy, then the shortest path.
    bool sprintTrade(std::string& path) {
        Board const& b = w_.board;
        int cap = std::min(p_.sprintMax, maxSteps(L_)); // Allow any dragon (even growers) to set sprint traps if tradeOk
        if (cap < 2) return false;
        std::vector<int> blk = ownBlk();
        // BFS over tiles free right now (blk <= 1: no dragon, not our body).
        std::vector<int> dist(b.NC, INF), from(b.NC, -1), dirTo(b.NC, -1);
        std::vector<int> q{w_.head};
        dist[w_.head] = 0;
        for (size_t qi = 0; qi < q.size(); qi++) {
            int c = q[qi];
            if (dist[c] + 1 >= cap) continue;  // the last step goes onto the head itself
            for (int d = 0; d < 4; d++) {
                int n = b.nb[c * 4 + d];
                if (n < 0 || dist[n] != INF || blk[n] > 1) continue;
                dist[n] = dist[c] + 1;
                from[n] = c;
                dirTo[n] = d;
                q.push_back(n);
            }
        }
        int bestLen = -1, bestSteps = INF, bestEnd = -1, bestDir = -1;
        for (EnemyField const& e : enemies_) {
            if (e.visible < 2) continue;
            bool allowed = huntAt(e.head) != nullptr || tradeOk(L_, e.visible);
            // Assassinate even without local support if the enemy is very long/dangerous
            bool forceAssassinate = e.visible >= L_ + 2;
            if (!allowed || (!localOk(e.head, e.id) && !forceAssassinate)) continue;
            for (int d = 0; d < 4; d++) {
                // stand on `pre`, step d onto the head
                int pre = -1;
                for (int k = 0; k < 4; k++) {
                    int n = b.nb[e.head * 4 + k];
                    if (n >= 0 && b.nb[n * 4 + d] == e.head) pre = n;
                }
                if (pre < 0 || dist[pre] == INF) continue;
                int steps = dist[pre] + 1;
                if (steps < 2 || steps > cap) continue;
                if (e.visible > bestLen || (e.visible == bestLen && steps < bestSteps)) {
                    bestLen = e.visible;
                    bestSteps = steps;
                    bestEnd = pre;
                    bestDir = d;
                }
            }
        }
        if (bestEnd < 0) return false;
        std::string rev(1, DCH[bestDir]);
        for (int c = bestEnd; c != w_.head; c = from[c]) rev += DCH[dirTo[c]];
        path.assign(rev.rbegin(), rev.rend());
        return true;
    }

    bool hasRoomyMove(int head, std::vector<int> const& blk, int len) {
        Board const& b = w_.board;
        int need = std::min(std::max(static_cast<int>(p_.spaceFactor * len) + p_.spaceMargin, p_.splitRoom), b.NC / 2);
        for (int d = 0; d < 4; d++) {
            int n = b.nb[head * 4 + d];
            if (n < 0 || blk[n] > 1) continue;
            if (nav_.flood(b, n, blk, need + 1) >= need) return true;
        }
        return false;
    }
};

}  // namespace bc

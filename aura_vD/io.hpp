#pragma once

#include "common.hpp"

namespace bc {

struct VisTile {
    int x, y;
    bool pearl;
    int pearlIn;  // -1: not a pearl bed
};

struct Part {
    char team;
    int id, x, y, facing;
    bool head;
};

struct EdgeObs {
    int8_t kind;  // 0 empty, 1 kelp, 2 portal
    int16_t pid;
};

struct Init {
    int id = -1;
    char team = 'A';
    int w = 0, h = 0;
    int unitLimit = 64;
};

struct Turn {
    int round = 0, dir = 0, length = 2, units = 1;
    std::vector<uint64_t> msgs;
    int echoes[5] = {0, 0, 0, 0, 0};
    VisTile tiles[49];
    std::vector<Part> parts;
    EdgeObs hRows[8][7];  // hRows[r][c]: top edge of vision tile (c, r); r = 7 is the bottom row's south edge
    EdgeObs vRows[7][8];  // vRows[r][c]: left edge of vision tile (c, r); c = 7 is the right column's east edge
};

// Line reader over stdin. Never throws: on EOF next() returns false.
class Reader {
  public:
    bool next() {
        for (;;) {
            if (!std::fgets(buf_, sizeof buf_, stdin)) return false;
            if (char* hash = std::strchr(buf_, '#')) *hash = '\0';
            count_ = 0;
            char* p = buf_;
            while (*p && count_ < kMaxTok) {
                while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') *p++ = '\0';
                if (!*p) break;
                tok_[count_++] = p;
                while (*p && *p != ' ' && *p != '\t' && *p != '\r' && *p != '\n') p++;
            }
            if (count_ > 0) return true;
        }
    }
    int count() const { return count_; }
    char const* str(int i) const { return i < count_ ? tok_[i] : ""; }
    int num(int i) const { return i < count_ ? std::atoi(tok_[i]) : 0; }
    bool is(char const* label) const { return count_ > 0 && std::strcmp(tok_[0], label) == 0; }

  private:
    static constexpr int kMaxTok = 16;
    char buf_[512];
    char* tok_[kMaxTok];
    int count_ = 0;
};

inline EdgeObs parseEdge(char const* s) {
    if (s[0] == '.') return {0, -1};
    if (s[0] == 'w') return {1, -1};
    return {2, static_cast<int16_t>(std::atoi(s))};
}

inline bool readInit(Reader& in, Init& out) {
    for (int got = 0; got < 4;) {
        if (!in.next()) return false;
        if (in.is("ID")) out.id = in.num(1), got++;
        else if (in.is("TEAM")) out.team = in.str(1)[0], got++;
        else if (in.is("MAP")) out.w = in.num(1), out.h = in.num(2), got++;
        else if (in.is("UNIT_LIMIT")) out.unitLimit = in.num(1), got++;
    }
    return true;
}

// Returns false on EOF or ENDGAME.
inline bool readTurn(Reader& in, Turn& t) {
    do {
        if (!in.next()) return false;
        if (in.is("ENDGAME")) return false;
    } while (!in.is("ROUND"));
    t.round = in.num(1);
    if (!in.next()) return false;
    t.dir = std::max(0, dirFromChar(in.str(1)[0]));
    if (!in.next()) return false;
    t.length = in.num(1);
    if (!in.next()) return false;
    t.units = in.num(1);
    if (!in.next()) return false;
    int msgs = in.num(1);
    t.msgs.clear();
    for (int i = 0; i < msgs; i++) {
        if (!in.next()) return false;
        t.msgs.push_back(static_cast<uint64_t>(std::strtoull(in.str(0), nullptr, 10)));
    }
    for (int i = 0; i < 5; i++) t.echoes[i] = 0;
    for (int i = 0; i < 49; i++) {
        if (!in.next()) return false;
        if (i == 0 && in.is("ECHOES")) {
            for (int j = 0; j < 5; j++) t.echoes[j] = in.num(j + 1);
            if (!in.next()) return false;
        }
        t.tiles[i] = {in.num(0), in.num(1), in.num(2) == 1, in.num(3)};
    }
    if (!in.next()) return false;
    int parts = in.num(1);
    t.parts.clear();
    for (int i = 0; i < parts; i++) {
        if (!in.next()) return false;
        t.parts.push_back({in.str(0)[0], in.num(1), in.num(2), in.num(3), std::max(0, dirFromChar(in.str(4)[0])),
                           in.num(5) == 1});
    }
    for (int r = 0; r < 8; r++) {
        if (!in.next()) return false;
        for (int c = 0; c < 7; c++) t.hRows[r][c] = parseEdge(in.str(c));
    }
    for (int r = 0; r < 7; r++) {
        if (!in.next()) return false;
        for (int c = 0; c < 8; c++) t.vRows[r][c] = parseEdge(in.str(c));
    }
    return true;
}

// Everything for one turn goes out in a single write: writes cost 2.5M points each.
struct Out {
    std::string buf;
    void move(int d) { buf += "MOVE "; buf += DCH[d]; buf += '\n'; }
    void moveSeq(std::string const& dirs) { buf += "MOVE " + dirs + '\n'; }
    void split(int n) { buf += "SPLIT " + std::to_string(n) + '\n'; }
    void ping(uint64_t signature, char dir) { buf += "SONAR " + std::string(1, dir) + " " + std::to_string(signature) + '\n'; }
    void log(std::string const& s) {
#ifdef BC_DEBUG
        buf += "LOG " + s + '\n';
#else
        (void)s;
#endif
    }
    void flush() {
        buf += "PROTOCOL 3\nENDTURN\n";
        std::fwrite(buf.data(), 1, buf.size(), stdout);
        std::fflush(stdout);
        buf.clear();
    }
};

}  // namespace bc

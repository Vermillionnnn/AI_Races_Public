// 数织唯一解证明器：单行推理、试填、完整搜索和难度评级（prove.cpp 使用）。
#pragma once
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>
#include "fast_line.h"

using U = std::uint64_t;
using Clock = std::chrono::steady_clock;
static U mask(int n) { return (U(1)<<n)-1; }
static int pc(U x) { int n=0; while(x) { x&=x-1; ++n; } return n; }
static int bit(U x) {
    static constexpr int table[64]={0,1,48,2,57,49,28,3,61,58,50,42,38,29,17,4,62,55,59,36,53,51,43,22,45,39,33,30,24,18,12,5,63,47,56,27,60,41,37,16,54,35,52,21,44,32,23,11,46,26,40,15,34,20,31,10,25,14,19,9,13,8,7,6};
    return table[((x&(~x+1))*0x03f79d71b4cb0a89ULL)>>58];
}
static U mix(U x) { x=(x^(x>>30))*0xbf58476d1ce4e5b9ULL; x=(x^(x>>27))*0x94d049bb133111ebULL; return x^(x>>31); }
static double elapsed(Clock::time_point t) { return std::chrono::duration<double,std::milli>(Clock::now()-t).count(); }

struct Clue {
    std::vector<int> a;
    U code=0;
    explicit Clue(U line=0) {
        int pos=0;
        while(line) {
            while(!(line&1)) line>>=1;
            int run=0; while(line&1) { ++run; line>>=1; }
            a.push_back(run); code|=mask(run)<<pos; pos+=run+1;
        }
    }
};
static Clue makeClue(const std::vector<int>& a,int n) {
    int span=a.empty()?0:int(a.size())-1;for(int v:a){if(v<1 || v>n)throw std::runtime_error("invalid clue length");span+=v;}
    if(span>n)throw std::runtime_error("clues do not fit the line");
    Clue c;c.a=a;int pos=0;for(int v:a){c.code|=mask(v)<<pos;pos+=v+1;}return c;
}
struct LineResult { bool ok=false; U b=0,w=0,ways=0; };

// Exact line-domain filtering. F/G describe paths through all legal run placements.
static LineResult lineSolve(int n, const Clue& clue, U b, U w) {
    if(b&w || ((b|w)&~mask(n))) return {};
    const int k=int(clue.a.size());
    if(k>25) return {};
    std::array<U,25> runs{};
    for(int j=0;j<k;++j) runs[j]=mask(clue.a[j]);
    U F[51][26]={}; unsigned char G[51][26]={};
    auto fits=[&](int i,int j) {
        int end=i+clue.a[j];
        return end<=n && !((runs[j]<<i)&w) && (end==n || !(b&(U(1)<<end)));
    };
    F[0][0]=1;
    for(int i=0;i<n;++i) for(int j=0;j<=k;++j) if(F[i][j]) {
        if(!(b&(U(1)<<i))) F[i+1][j]+=F[i][j];
        if(j<k && fits(i,j)) F[std::min(n,i+clue.a[j]+1)][j+1]+=F[i][j];
    }
    if(!F[n][k]) return {};
    G[n][k]=1;
    for(int i=n-1;i>=0;--i) for(int j=k;j>=0;--j) {
        if(!(b&(U(1)<<i)) && G[i+1][j]) G[i][j]=1;
        if(j<k && fits(i,j) && G[std::min(n,i+clue.a[j]+1)][j+1]) G[i][j]=1;
    }
    U canB=0,canW=0;
    for(int i=0;i<n;++i) for(int j=0;j<=k;++j) if(F[i][j]) {
        if(!(b&(U(1)<<i)) && G[i+1][j]) canW|=U(1)<<i;
        if(j<k && fits(i,j) && G[std::min(n,i+clue.a[j]+1)][j+1]) {
            canB|=runs[j]<<i;
            if(i+clue.a[j]<n) canW|=U(1)<<(i+clue.a[j]);
        }
    }
    return {true,mask(n)&~canW,mask(n)&~canB,F[n][k]};
}
static LineResult fastLineSolve(int n,const Clue& clue,U b,U w) {
    if(b&w || ((b|w)&~mask(n)))return {};
    nonogen_fast::Clue c;c.n=n;c.k=int(clue.a.size());c.full=mask(n);
    for(int j=0;j<c.k;++j)c.len[j]=clue.a[j];
    U outB=0,outW=0;
    bool ok=nonogen_fast::lineSolve(c,b,w,outB,outW);
    return {ok,outB,outW,0}; // The bitset filter does not count placements.
}
struct Puzzle { int h=0,w=0; std::vector<Clue> clues; };
struct Board {
    int n; std::array<U,100> m{};
    explicit Board(int size=0):n(size){}
    void flip(int cell) {int r=cell/n,c=cell%n; m[r]^=U(1)<<c; m[n+c]^=U(1)<<r;}
    bool value(int cell) const {return bool(m[cell/n]&(U(1)<<(cell%n)));}
    U hash() const {U h=0;for(int i=0;i<n;++i) h=mix(h^mix(m[i]+U(i)));return h;}
    Puzzle puzzle() const {Puzzle p;p.h=p.w=n; for(int i=0;i<2*n;++i) p.clues.emplace_back(m[i]);return p;}
};
struct State { std::array<U,100> b{},w{}; };
struct Counters { U lines=0,dp=0,hits=0,nodes=0; };
struct CacheKey {
    U clue,b,w;
    bool operator==(const CacheKey& x) const {return clue==x.clue && b==x.b && w==x.w;}
};
struct CacheHash {std::size_t operator()(const CacheKey& k) const {return mix(k.clue^mix(k.b)^mix(k.w+0x9e3779b97f4a7c15ULL));}};
struct Limit {};

class Engine {
    std::vector<std::unordered_map<CacheKey,LineResult,CacheHash>> cache;
    U cap=~U(0);
    Clock::time_point deadline=Clock::time_point::max();
public:
    Puzzle p;
    Counters stats;
    bool useCache=true,fastFilter=false;
    explicit Engine(Puzzle puzzle,bool caching=true,bool fast=false):cache(puzzle.h+puzzle.w),p(std::move(puzzle)),useCache(caching),fastFilter(fast){}
    void budget(U work,double seconds=0) {cap=stats.lines+work;deadline=seconds>0?Clock::now()+std::chrono::duration_cast<Clock::duration>(std::chrono::duration<double>(seconds)):Clock::time_point::max();}
    void tightenBudget(U work) {cap=stats.lines+std::min(work,cap-stats.lines);}
    void checkpoint() const {if(stats.lines>=cap || Clock::now()>=deadline) throw Limit{};}
    LineResult line(int idx,U b,U w) {
        if(stats.lines>=cap) throw Limit{};
        if((stats.lines&1023)==0 && Clock::now()>=deadline) throw Limit{};
        ++stats.lines;
        CacheKey key{p.clues[idx].code,b,w};
        if(useCache) {
            auto it=cache[idx].find(key);
            if(it!=cache[idx].end()) {++stats.hits;return it->second;}
        }
        ++stats.dp; auto result=fastFilter?fastLineSolve(idx<p.h?p.w:p.h,p.clues[idx],b,w):lineSolve(idx<p.h?p.w:p.h,p.clues[idx],b,w);
        if(useCache) {if(cache[idx].size()>=512) cache[idx].clear();cache[idx].emplace(key,result);}
        return result;
    }
    bool assign(State& s,int cell,bool v) const {
        int r=cell/p.w,c=cell%p.w; U x=U(1)<<c,y=U(1)<<r;
        if(v) {if(s.w[r]&x) return false;s.b[r]|=x;s.b[p.h+c]|=y;}
        else {if(s.b[r]&x) return false;s.w[r]|=x;s.w[p.h+c]|=y;}
        return true;
    }
    bool propagate(State& s,int cell=-1) {
        std::vector<int> q; q.reserve(256); std::array<bool,100> queued{};
        auto add=[&](int i){if(!queued[i]) {queued[i]=true;q.push_back(i);}};
        if(cell<0) for(int i=0;i<p.h+p.w;++i) add(i);
        else {add(cell/p.w);add(p.h+cell%p.w);}
        std::size_t head=0;
        for(;;) {
            for(;head<q.size();++head) {
                int i=q[head];queued[i]=false;
                auto res=line(i,s.b[i],s.w[i]);if(!res.ok) return false;
                U moreB=res.b&~s.b[i],moreW=res.w&~s.w[i];
                s.b[i]|=res.b;s.w[i]|=res.w;
                for(U t=moreB;t;t&=t-1) {int j=bit(t);if(i<p.h){s.b[p.h+j]|=U(1)<<i;add(p.h+j);}else{s.b[j]|=U(1)<<(i-p.h);add(j);}}
                for(U t=moreW;t;t&=t-1) {int j=bit(t);if(i<p.h){s.w[p.h+j]|=U(1)<<i;add(p.h+j);}else{s.w[j]|=U(1)<<(i-p.h);add(j);}}
            }
            if(!countRule) return true;
            int k=boundaryRule(s,0,add);if(k<0)return false;
            if(!k){k=boundaryRule(s,1,add);if(k<0)return false;}
            if(!k) return true;
        }
    }
    // Cross-line counting (optional, --count-rule). Pad each line with white cells
    // on both ends. At boundary i between positions i-1 and i, the number of runs
    // starting there minus the number ending there equals mass[i]-mass[i-1], where
    // mass is the black count of the perpendicular line (its clue sum). Runs over
    // all lines start exactly R times in total (R = number of clue blocks). Bounds
    // on starts/ends per boundary that become tight force or forbid starts/ends.
    bool countRule=false;
    std::array<int,51> massR{},massC{};int runsR=0,runsC=0;
    void enableCountRule() {
        countRule=true;
        for(int i=0;i<p.h;++i){runsR+=int(p.clues[i].a.size());for(int v:p.clues[i].a)massR[i]+=v;}
        for(int i=0;i<p.w;++i){runsC+=int(p.clues[p.h+i].a.size());for(int v:p.clues[p.h+i].a)massC[i]+=v;}
    }
    template<class Add> int boundaryRule(State& s,int o,Add& add) {
        int nl=o?p.w:p.h,len=o?p.h:p.w,R=o?runsC:runsR;const auto& mass=o?massR:massC;
        U all=mask(len+1);
        std::array<int,51> minS{},maxS{},minE{},maxE{};
        std::array<U,50> PS{},DS{},PE{},DE{},CB{},CW{},PB{},PW{};
        for(int l=0;l<nl;++l) {
            int idx=o?p.h+l:l;U B=s.b[idx],W=s.w[idx];
            U curB=B,curW=W|(U(1)<<len),prvB=B<<1,prvW=(W<<1)|1;
            CB[l]=curB;CW[l]=curW;PB[l]=prvB;PW[l]=prvW;
            PS[l]=~curW&~prvB&all;DS[l]=curB&prvW&all;PE[l]=~prvW&~curB&all;DE[l]=prvB&curW&all;
            for(U t=PS[l];t;t&=t-1)++maxS[bit(t)];
            for(U t=DS[l];t;t&=t-1)++minS[bit(t)];
            for(U t=PE[l];t;t&=t-1)++maxE[bit(t)];
            for(U t=DE[l];t;t&=t-1)++minE[bit(t)];
        }
        std::array<int,51> lo{},hi{};long long sumLo=0,sumHi=0;
        for(int i=0;i<=len;++i) {
            int d=(i<len?mass[i]:0)-(i>0?mass[i-1]:0);
            lo[i]=std::max({minS[i],d+minE[i],0});hi[i]=std::min(maxS[i],d+maxE[i]);
            if(lo[i]>hi[i])return -1;sumLo+=lo[i];sumHi+=hi[i];
        }
        if(sumLo>R || sumHi<R)return -1;
        int changed=0;
        auto set=[&](int l,int pos,bool v)->bool{
            int cell=o?pos*p.w+l:l*p.w+pos;int r=cell/p.w,c=cell%p.w;U x=U(1)<<c;
            if((v?s.b[r]:s.w[r])&x)return true;
            if(!assign(s,cell,v))return false;add(r);add(p.h+c);++changed;return true;
        };
        for(int i=0;i<=len;++i) {
            int d=(i<len?mass[i]:0)-(i>0?mass[i-1]:0);
            long long H=std::min<long long>(hi[i],R-(sumLo-lo[i])),L=std::max<long long>(lo[i],R-(sumHi-hi[i]));
            if(L>H)return -1;
            U bitI=U(1)<<i;
            for(int l=0;l<nl;++l) {
                bool ps=PS[l]&bitI,ds=DS[l]&bitI,pe=PE[l]&bitI,de=DE[l]&bitI;
                if(ps && !ds) {
                    if(L==maxS[i]) {if(i<len && !set(l,i,true))return -1;if(i>0 && !set(l,i-1,false))return -1;}
                    else if(H==minS[i]) {
                        if(CB[l]&bitI){if(i==0 || !set(l,i-1,true))return -1;}
                        else if(PW[l]&bitI){if(i==len || !set(l,i,false))return -1;}
                    }
                }
                if(pe && !de) {
                    if(L-d==maxE[i]) {if(i>0 && !set(l,i-1,true))return -1;if(i<len && !set(l,i,false))return -1;}
                    else if(H-d==minE[i]) {
                        if(PB[l]&bitI){if(i==len || !set(l,i,true))return -1;}
                        else if(CW[l]&bitI){if(i==0 || !set(l,i-1,false))return -1;}
                    }
                }
            }
        }
        return changed;
    }
    int fixed(const State& s) const {int c=0;for(int r=0;r<p.h;++r)c+=pc(s.b[r]|s.w[r]);return c;}
    double entropy(const State& s) {
        if(fastFilter)throw std::runtime_error("placement counting requires the counting DP");
        double result=0;
        for(int i=0;i<p.h+p.w;++i) {auto r=line(i,s.b[i],s.w[i]);if(!r.ok)throw std::runtime_error("inconsistent fitness state");result+=std::log2(double(r.ways));}
        return result;
    }
    int branch(const State& s) const {
        std::array<int,100> unknown{};
        for(int i=0;i<p.h+p.w;++i) unknown[i]=(i<p.h?p.w:p.h)-pc(s.b[i]|s.w[i]);
        int best=-1,score=-1;
        for(int r=0;r<p.h;++r) for(U t=mask(p.w)&~(s.b[r]|s.w[r]);t;t&=t-1) {
            int c=bit(t),v=1024/unknown[r]+1024/unknown[p.h+c];
            if(v>score) {score=v;best=r*p.w+c;}
        }
        return best;
    }
    // Search the complete residual tree for an answer DIFFERENT from the known answer.
    // Finding none is an exact uniqueness proof, not a sample of search branches.
    bool alternative(State s,const Board& known,Board& witness,bool different=false) {
        ++stats.nodes;
        for(int r=0;r<p.h && !different;++r)
            different=bool((s.b[r]&~known.m[r]) | (s.w[r]&known.m[r]));
        int cell=branch(s);
        if(cell<0) {if(!different)return false;witness=Board(p.h);for(int r=0;r<p.h;++r)for(U t=s.b[r];t;t&=t-1)witness.flip(r*p.w+bit(t));return true;}
        for(bool v:{known.value(cell),!known.value(cell)}) {
            State child=s;assign(child,cell,v);
            if(propagate(child,cell) && alternative(child,known,witness,different)) return true;
        }
        return false;
    }
    // Failed-literal filtering is sound even when search has ruled out the target.
    // A surviving probe is only a possibility; it never certifies uniqueness.
    bool probe(State& s,const Board& known,Board& witness,bool& found) {
        bool progress=true;
        while(progress) {
            progress=false;
            for(int r=0;r<p.h;++r) for(int c=0;c<p.w;++c) {
                U pos=U(1)<<c;if((s.b[r]|s.w[r])&pos)continue;
                int cell=r*p.w+c;State trial=s;assign(trial,cell,!known.value(cell));
                if(!propagate(trial,cell)) {
                    assign(s,cell,known.value(cell));if(!propagate(s,cell))return false;progress=true;
                } else if(fixed(trial)==p.h*p.w) {
                    witness=Board(p.h);
                    for(int rr=0;rr<p.h;++rr)for(U t=trial.b[rr];t;t&=t-1)witness.flip(rr*p.w+bit(t));
                    found=true;return true;
                }
            }
        }
        return true;
    }
    // Difficulty must not use the answer: probe BOTH colors, keep common
    // consequences, and repeat through every unknown cell to a fixed point.
    bool probeAll(State& s,int& best,int scoreScale=4096) {
        bool progress=true;
        while(progress) {
            progress=false;best=-1;long long bestScore=-1;
            for(int r=0;r<p.h;++r) for(int c=0;c<p.w;++c) {
                U pos=U(1)<<c;if((s.b[r]|s.w[r])&pos)continue;
                int cell=r*p.w+c;State black=s,white=s;
                assign(black,cell,true);bool okB=propagate(black,cell);
                assign(white,cell,false);bool okW=propagate(white,cell);
                if(!okB && !okW)return false;
                if(!okB || !okW) {s=okB?black:white;progress=true;continue;}
                bool changed=false;int nb=0,nw=0;
                for(int rr=0;rr<p.h;++rr) {
                    U unk=mask(p.w)&~(s.b[rr]|s.w[rr]);
                    nb+=pc((black.b[rr]|black.w[rr])&unk);
                    nw+=pc((white.b[rr]|white.w[rr])&unk);
                    U cb=black.b[rr]&white.b[rr]&unk,cw=black.w[rr]&white.w[rr]&unk;
                    for(U t=cb;t;t&=t-1){assign(s,rr*p.w+bit(t),true);changed=true;}
                    for(U t=cw;t;t&=t-1){assign(s,rr*p.w+bit(t),false);changed=true;}
                }
                if(changed) {if(!propagate(s))return false;progress=true;continue;}
                long long score=std::min(nb,nw)*static_cast<long long>(scoreScale)+nb+nw;
                if(score>bestScore){bestScore=score;best=cell;}
            }
        }
        return true;
    }
    bool alternativeFull(State s,const Board& known,Board& witness,int best,bool first=true) {
        ++stats.nodes;
        if(!first && !probeAll(s,best))return false;
        if(fixed(s)==p.h*p.w) {
            bool different=false;for(int r=0;r<p.h;++r)different|=s.b[r]!=known.m[r];
            if(!different)return false;
            witness=Board(p.h);for(int r=0;r<p.h;++r)for(U t=s.b[r];t;t&=t-1)witness.flip(r*p.w+bit(t));return true;
        }
        if(best<0)best=branch(s);
        for(bool v:{known.value(best),!known.value(best)}) {
            State child=s;assign(child,best,v);
            if(propagate(child,best) && alternativeFull(child,known,witness,-1,false))return true;
        }
        return false;
    }
    int count(State s,int stop=2) {
        ++stats.nodes;int cell=branch(s);if(cell<0)return 1;
        int total=0;
        for(bool v:{true,false}) {State child=s;assign(child,cell,v);if(propagate(child,cell))total+=count(child,stop-total);if(total>=stop)break;}
        return total;
    }
    bool rectangleWitness(const State& s,const Board& known,Board& witness) const {
        int examined=0;
        for(int a=0;a<p.h;++a) for(int b=a+1;b<p.h;++b) {
            U available=mask(p.w)&~(s.b[a]|s.w[a]|s.b[b]|s.w[b]);
            U left=available&known.m[a]&~known.m[b],right=available&known.m[b]&~known.m[a];
            for(U x=left;x;x&=x-1) for(U y=right;y;y&=y-1) {
                if(++examined>512) return false;
                int c=bit(x),d=bit(y);U rm=(U(1)<<c)|(U(1)<<d),cm=(U(1)<<a)|(U(1)<<b);
                if(Clue(known.m[a]^rm).code!=p.clues[a].code || Clue(known.m[b]^rm).code!=p.clues[b].code ||
                   Clue(known.m[p.h+c]^cm).code!=p.clues[p.h+c].code || Clue(known.m[p.h+d]^cm).code!=p.clues[p.h+d].code) continue;
                witness=known;for(int r:{a,b})for(int col:{c,d})witness.flip(r*p.w+col);return true;
            }
        }
        return false;
    }
};

struct Difficulty {
    int lineRemaining=-1,probeRemaining=-1,best=-1;
    bool complete=false;
    State lineState,probeState;
    char tier() const {return !complete?'?':lineRemaining==0?'L':probeRemaining==0?'P':'S';}
};
static Difficulty rate(Engine& e) {
    Difficulty d;
    if(!e.propagate(d.lineState))throw std::runtime_error("rating rejected known answer");
    d.lineRemaining=e.p.h*e.p.w-e.fixed(d.lineState);
    d.probeState=d.lineState;
    if(d.lineRemaining && !e.probeAll(d.probeState,d.best))throw std::runtime_error("rating probes rejected known answer");
    d.probeRemaining=e.p.h*e.p.w-e.fixed(d.probeState);d.complete=true;return d;
}

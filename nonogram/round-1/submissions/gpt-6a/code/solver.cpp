#include <algorithm>
#include <array>
#include <bit>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <iostream>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>
using U = std::uint64_t;
struct Puzzle { std::string id; int h,w; int priority=0; std::vector<std::vector<int>> clues; };
// Exact line constraint propagation. Every bit denotes a possible boundary
// position, so all placements of one run are processed together.
struct Line {
    int n;
    U cells;
    std::vector<int> clue;
    Line(int n_, const std::vector<int>& c): n(n_),cells((U(1)<<n_)-1),clue(c) {}
    // One cache per worker, shared by its lines and reused across puzzles.
    // Inputs use at most 45 bits; the remaining 19 bits identify the line.
    // A worker has only one active puzzle (at most 90 live line identifiers).
    struct alignas(32) SharedEntry {U b=0,w=0,nb=0,nw=0;};
    static std::vector<SharedEntry>& sharedCache() {
        static thread_local std::vector<SharedEntry> table(U(1)<<16);
        return table;
    }
    static U nextStamp() {
        static thread_local U stamp=0;
        if(++stamp==(U(1)<<19)) {
            stamp=1;
            for(auto& entry:sharedCache())entry.b=0;
        }
        return stamp;
    }
    U stamp=nextStamp(),tag=stamp<<45,salt=stamp*0x94d049bb133111ebULL;
    SharedEntry* table=sharedCache().data();
    bool solve(U b,U w,U& nb,U& nw) {
        U key=(b*0x9e3779b97f4a7c15ULL)^(w*0xbf58476d1ce4e5b9ULL);
        key^=salt;
        auto& c=table[(key^(key>>32))&((U(1)<<16)-1)];
        if(c.b==(b|tag)&&c.w==w){nb=c.nb;nw=c.nw;return nb!=~U(0);}
        bool ok=compute(b,w,nb,nw);
        c={b|tag,w,ok?nb:~U(0),ok?nw:0};return ok;
    }
    bool compute(U b,U w,U& nb,U& nw) const {
        if((b|w)==cells){
            U remaining=b;
            for(int len:clue){
                if(!remaining)return false;
                remaining>>=std::countr_zero(remaining);
                if(std::countr_one(remaining)!=len)return false;
                remaining>>=len;
            }
            if(remaining)return false;
            nb=b;nw=w;return true;
        }
        const int k=static_cast<int>(clue.size());
        U f[47],allowed[46],canBlack=0,canWhite=0;
        // Append a white sentinel at n, allowing every run to consume its
        // mandatory separator uniformly. Boundary n+1 is the accepting state.
        U barrier=b<<1,limit=(U(1)<<(n+2))-1;
        // Seeds follow a legal white separator and never overlap barrier.
        // Subtraction spreads each seed rightward up to the next barrier.
        auto right=[&](U x){return (((barrier-x)|x)&~barrier)&limit;};
        // Reverse white closure, using six parallel doubling steps.
        U m1=(~b)&limit,m2=m1&(m1>>1),m4=m2&(m2>>2),m8=m4&(m4>>4),m16=m8&(m8>>8),m32=m16&(m16>>16);
        auto left=[&](U x){
            x|=(x>>1)&m1;x|=(x>>2)&m2;
            x|=(x>>4)&m4;x|=(x>>8)&m8;x|=(x>>16)&m16;x|=(x>>32)&m32;
            return x;
        };
        f[0]=right(1);
        // Reuse legal-start masks for repeated run lengths.
        U memo[46],seen=0;
        for(int j=0;j<k;++j){
            int len=clue[j];U tag=U(1)<<len;
            if(!(seen&tag)){
                U bad=w;int span=1;
                while(span*2<=len){bad|=bad>>span;span*=2;}
                if(span<len)bad|=bad>>(len-span);
                memo[len]=~bad&~(b>>len)&((U(1)<<(n-len+1))-1);seen|=tag;
            }
            allowed[j]=memo[len];
            f[j+1]=right((f[j]&allowed[j])<<(len+1));
            if(!f[j+1])return false;
        }
        if(!(f[k]&(U(1)<<(n+1))))return false;
        // Intersect prefix and suffix reachability to find supported colors.
        U g=left(U(1)<<(n+1));
        canWhite|=f[k]&(g>>1);
        for(int j=k-1;j>=0;--j){
            int len=clue[j];U suffix=allowed[j]&(g>>(len+1));
            U starts=f[j]&suffix;
            canWhite|=starts<<len;
            U coverage=starts;int span=1;
            while(span*2<=len){coverage|=coverage<<span;span*=2;}
            if(span<len)coverage|=coverage<<(len-span);
            canBlack|=coverage;
            g=left(suffix);
            canWhite|=f[j]&(g>>1);
        }
        canWhite&=~b;
        nb=cells&~canWhite;nw=cells&~canBlack;
        return true;
    }
};
// Rows and columns both have black/white masks; updates keep them in sync.
struct Board { std::array<U,90> b{},w{}; U dirty[2]={0,0}; int known=0; U touched=0; };
struct Solver {
    const Puzzle& p;
    std::vector<Line> lines;
    Solver(const Puzzle& q):p(q) { lines.reserve(p.h+p.w); for(int i=0;i<p.h+p.w;++i) lines.emplace_back(i<p.h?p.w:p.h,p.clues[i]); }
    void set(Board& s,int r,int c,bool black) {
        U x=U(1)<<c,y=U(1)<<r;
        if((s.b[r]|s.w[r])&x) return;
        if(black) {s.b[r]|=x;s.b[p.h+c]|=y;} else {s.w[r]|=x;s.w[p.h+c]|=y;}
        ++s.known;s.touched|=y;s.dirty[0]|=y;s.dirty[1]|=x;
    }
    bool propagate(Board& s) {
        int axis=0;
        while(s.dirty[0]||s.dirty[1]) {
            if(!s.dirty[axis]) axis^=1;
            U pending=s.dirty[axis]; s.dirty[axis]=0;
            while(pending) {
                int k=std::countr_zero(pending);pending&=pending-1;
                int l=axis?p.h+k:k;
                U nb,nw;
                if(!lines[l].solve(s.b[l],s.w[l],nb,nw)) return false;
                U diff=(nb|nw)&~(s.b[l]|s.w[l]);
                s.known+=std::popcount(diff);s.b[l]=nb;s.w[l]=nw;
                if(diff)s.touched|=axis?diff:(U(1)<<k);
                while(diff) {
                    int j=std::countr_zero(diff);diff&=diff-1;
                    int cross=axis?j:p.h+j;
                    if(nb&(U(1)<<j)) s.b[cross]|=U(1)<<k;else s.w[cross]|=U(1)<<k;
                    s.dirty[axis^1]|=U(1)<<j;
                }
            }
            axis^=1;
        }
        return true;
    }
    // Failed-literal probing plus constructive disjunction. If neither color
    // fails, every fact shared by both closures holds without an assumption.
    // At a fixed point, recurse on the split with largest gain product.
    bool dfs(Board& s) {
        if(!propagate(s)) return false;
        while(s.known<p.h*p.w) {
            int before=s.known;
            int bestScore=-1; Board bestA,bestB;
            struct Candidate {std::uint8_t r,c;std::uint16_t score;};
            std::vector<Candidate> candidates; candidates.reserve(p.h*p.w-s.known);
            int counts[90];for(int l=0;l<p.h+p.w;++l)counts[l]=std::popcount(s.b[l]|s.w[l]);
            for(int r=0;r<p.h;++r) {
                U unknown=lines[r].cells&~(s.b[r]|s.w[r]);
                while(unknown) {
                    int c=std::countr_zero(unknown);unknown&=unknown-1;
                    int score=counts[r]+counts[p.h+c];
                    int near=0;
                    if(r==0||((s.b[r-1]|s.w[r-1])&(U(1)<<c)))++near;
                    if(r+1==p.h||((s.b[r+1]|s.w[r+1])&(U(1)<<c)))++near;
                    if(c==0||((s.b[r]|s.w[r])&(U(1)<<(c-1))))++near;
                    if(c+1==p.w||((s.b[r]|s.w[r])&(U(1)<<(c+1))))++near;
                    score=near*10+score;
                    candidates.push_back({static_cast<std::uint8_t>(r),static_cast<std::uint8_t>(c),static_cast<std::uint16_t>(score)});
                }
            }
            std::sort(candidates.begin(),candidates.end(),[](const Candidate& a,const Candidate& b){return a.score>b.score;});
            for(auto candidate:candidates) {
                int r=candidate.r,c=candidate.c;
                if((s.b[r]|s.w[r])&(U(1)<<c))continue;
                Board a=s,b=s;a.touched=0;b.touched=0;set(a,r,c,true);set(b,r,c,false);
                bool av,bv;
                av=propagate(a);bv=propagate(b);
                if(!av&&!bv)return false;
                if(av&&a.known==p.h*p.w){s=a;return true;}
                if(bv&&b.known==p.h*p.w){s=b;return true;}
                if(!av||!bv) {s=av?a:b;bestScore=-1;continue;}
                int gainA=a.known-s.known,gainB=b.known-s.known;
                int score=gainA*gainB;
                if(score>bestScore) {bestScore=score;bestA=a;bestB=b;}
                bool changed=false;
                U commonRows=a.touched&b.touched;
                while(commonRows) {
                    int rr=std::countr_zero(commonRows);commonRows&=commonRows-1;
                    U bothB=a.b[rr]&b.b[rr]&~s.b[rr],bothW=a.w[rr]&b.w[rr]&~s.w[rr];
                    while(bothB){int cc=std::countr_zero(bothB);bothB&=bothB-1;set(s,rr,cc,true);changed=true;}
                    while(bothW){int cc=std::countr_zero(bothW);bothW&=bothW-1;set(s,rr,cc,false);changed=true;}
                }
                if(changed){if(!propagate(s))return false;bestScore=-1;}
            }
            if(s.known>before)continue;
            if(bestScore<0)return false;
            if(bestA.known<bestB.known)std::swap(bestA,bestB);
            if(dfs(bestA)){s=bestA;return true;}
            if(dfs(bestB)){s=bestB;return true;}
            return false;
        }
        return true;
    }
    bool validate(const Board& s) const {
        for(int l=0;l<p.h+p.w;++l) {
            std::vector<int> c;int run=0;
            for(int i=0;i<lines[l].n;++i) {if(s.b[l]&(U(1)<<i)) ++run;else if(run) {c.push_back(run);run=0;}}
            if(run)c.push_back(run);
            if(c!=lines[l].clue)return false;
        }
        return true;
    }
    std::string run() {
        Board s;s.dirty[0]=(U(1)<<p.h)-1;s.dirty[1]=(U(1)<<p.w)-1;
        if(!dfs(s)||!validate(s))return "UNSOLVED "+p.id+"\n";
        std::string out="SOLUTION "+p.id+"\n";
        for(int r=0;r<p.h;++r) {for(int c=0;c<p.w;++c)out+=(s.b[r]&(U(1)<<c))?'#':'.';out+='\n';}
        return out;
    }
};
bool readPuzzle(Puzzle& p) {
    std::string head,line;if(!std::getline(std::cin,head))return false;
    while(head.empty()&&std::getline(std::cin,head)){}
    std::istringstream hs(head);std::string tag;
    if(!(hs>>tag>>p.id>>p.h>>p.w)||tag!="PUZZLE"||p.h<1||p.h>45||p.w<1||p.w>45)return false;
    p.clues.clear();p.clues.resize(p.h+p.w);
    p.priority=p.h*p.w;
    for(auto& c:p.clues) {
        if(!std::getline(std::cin,line))return false;
        c.reserve(24);int a=0;
        for(char ch:line){if(ch>='0'&&ch<='9')a=a*10+(ch-'0');else if(a){c.push_back(a);a=0;}}
        if(a)c.push_back(a);
    }
    return true;
}
int main() {
    std::ios::sync_with_stdio(false);
    std::cin.tie(nullptr);
    std::mutex queueMutex,outputMutex;
    std::condition_variable ready;
    std::deque<Puzzle> jobs;
    bool done=false;
    auto worker=[&] {
        // Initialize each worker's private cache before processing requests.
        (void)Line::sharedCache();
        for(;;) {
            Puzzle puzzle;
            {
                std::unique_lock<std::mutex> lock(queueMutex);
                ready.wait(lock,[&]{return done||!jobs.empty();});
                if(jobs.empty())return;
                // Start immediately; among puzzles already received, take larger ones first.
                auto pos=std::max_element(jobs.begin(),jobs.end(),
                    [](const Puzzle& a,const Puzzle& b){return a.priority<b.priority;});
                puzzle=std::move(*pos);
                jobs.erase(pos);
            }
            Solver solver(puzzle);
            std::string answer=solver.run();
            {
                std::lock_guard<std::mutex> lock(outputMutex);
                std::cout<<answer<<std::flush;
            }
        }
    };
    std::thread first(worker),second(worker);
    Puzzle puzzle;
    while(readPuzzle(puzzle)) {
        {
            std::lock_guard<std::mutex> lock(queueMutex);
            jobs.push_back(std::move(puzzle));
        }
        ready.notify_one();
    }
    {
        std::lock_guard<std::mutex> lock(queueMutex);
        done=true;
    }
    ready.notify_all();
    first.join();
    second.join();
    return 0;
}

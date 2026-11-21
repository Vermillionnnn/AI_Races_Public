// 独立的唯一解证明器：只有证明部分，不含出题。公开仓库里放的就是这个文件和 prover.h、fast_line.h。
//
//     g++ -O3 -std=c++17 prove.cpp -o prove
//     ./prove check-one [--proof-work N] [--max-seconds S] [--no-cache] [--count-rule] < 输入
//
// 输入：第一行 n（只收 n×n，长方形的题由 judge/unique.py 补全白行列垫成正方形），之后 2n 行线索
// （每行「块数 块长…」，先行后列），再 n 行答案（# 黑 . 白）。从全未知开始推理、试填、搜索，
// 找和答案不同的第二个解；所有分支都排除才算唯一。输出一行 JSON，字段见 main() 末尾。
#include "prover.h"

int main(int argc,char** argv) {
    try {
        U work=20000;double seconds=0;bool cache=true,countRule=false;
        int i=1;if(i<argc && std::string(argv[i])=="check-one")++i;
        for(;i<argc;++i) {
            std::string a=argv[i];
            if(a=="--no-cache"){cache=false;continue;}
            if(a=="--count-rule"){countRule=true;continue;}
            if(i+1>=argc)throw std::runtime_error("missing value for "+a);
            std::string v=argv[++i];
            if(a=="--proof-work")work=std::stoull(v);else if(a=="--max-seconds")seconds=std::stod(v);
            else throw std::runtime_error("unknown option "+a);
        }
        int n;if(!(std::cin>>n) || n<1 || n>50)throw std::runtime_error("invalid square size");
        Puzzle p;p.h=p.w=n;
        for(int k=0;k<2*n;++k) {
            int c;if(!(std::cin>>c) || c<0 || c>25)throw std::runtime_error("invalid clue count");
            std::vector<int> a(c);for(int& v:a)if(!(std::cin>>v))throw std::runtime_error("incomplete clues");
            p.clues.push_back(makeClue(a,n));
        }
        Board known(n);
        for(int r=0;r<n;++r) {
            std::string row;if(!(std::cin>>row) || int(row.size())!=n)throw std::runtime_error("invalid answer dimensions");
            for(int c=0;c<n;++c){if(row[c]=='#')known.flip(r*n+c);else if(row[c]!='.')throw std::runtime_error("invalid answer character");}
        }
        for(int k=0;k<2*n;++k)if(Clue(known.m[k]).code!=p.clues[k].code)throw std::runtime_error("answer does not satisfy clues");
        Engine engine(p,cache,true);if(countRule)engine.enableCountRule();engine.budget(work,seconds);
        auto start=Clock::now();bool unique=false,timeout=false;Difficulty d;
        try {
            d=rate(engine);Board witness(n);
            unique=!engine.alternativeFull(d.probeState,known,witness,d.best);
        } catch(const Limit&) {timeout=true;}
        std::cout<<"{\"unique\":"<<(timeout?"null":unique?"true":"false")<<",\"status\":\""<<(timeout?"timeout":unique?"unique":"multiple")
                 <<"\",\"tier\":"<<(unique&&!timeout?"\""+std::string(1,d.tier())+"\"":"null")
                 <<",\"difficulty\":{\"complete\":"<<(d.complete?"true":"false")<<",\"line_remaining\":"<<d.lineRemaining<<",\"probe_remaining\":"<<d.probeRemaining<<"}"
                 <<",\"ms\":"<<std::setprecision(10)<<elapsed(start)<<",\"lines\":"<<engine.stats.lines<<",\"dp_calls\":"<<engine.stats.dp
                 <<",\"cache_hits\":"<<engine.stats.hits<<",\"nodes\":"<<engine.stats.nodes<<"}\n";
        return timeout?2:0;
    } catch(const std::exception& e) {std::cerr<<"error: "<<e.what()<<"\n";return 1;}
}

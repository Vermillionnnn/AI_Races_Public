// Nonogram solver with tiers + event trace. Cells: -1 unknown, 0 white, 1 black.
function makePuzzle(rows, cols){ return {h: rows.length, w: cols.length, rows, cols}; }
function cluesOf(line){ const r=[]; let run=0; for(const v of line){ if(v) run++; else if(run){r.push(run);run=0;} } if(run) r.push(run); return r; }
function puzzleFromGrid(g){ const h=g.length,w=g[0].length; const rows=g.map(cluesOf); const cols=[]; for(let c=0;c<w;c++) cols.push(cluesOf(g.map(r=>r[c]))); return makePuzzle(rows,cols); }

// Complete line solver: returns null on contradiction, else new line array.
function solveLine(cells, clues){
  const n=cells.length, k=clues.length;
  const wpre=new Int32Array(n+1); for(let i=0;i<n;i++) wpre[i+1]=wpre[i]+(cells[i]===0?1:0);
  const fits=(s,L)=> s+L<=n && wpre[s+L]-wpre[s]===0 && (s+L===n || cells[s+L]!==1);
  const F=[]; for(let i=0;i<=n;i++) F.push(new Uint8Array(k+1)); F[0][0]=1;
  for(let i=0;i<n;i++) for(let j=0;j<=k;j++){ if(!F[i][j]) continue;
    if(cells[i]!==1) F[i+1][j]=1;
    if(j<k && fits(i,clues[j])) F[Math.min(i+clues[j]+1,n)][j+1]=1; }
  if(!F[n][k]) return null;
  const G=[]; for(let i=0;i<=n;i++) G.push(new Uint8Array(k+1)); G[n][k]=1;
  for(let i=n-1;i>=0;i--) for(let j=k;j>=0;j--){
    let v=0; if(cells[i]!==1 && G[i+1][j]) v=1;
    if(!v && j<k && fits(i,clues[j]) && G[Math.min(i+clues[j]+1,n)][j+1]) v=1;
    G[i][j]=v; }
  const canW=new Uint8Array(n), diff=new Int32Array(n+1);
  for(let i=0;i<n;i++) for(let j=0;j<=k;j++){
    if(F[i][j] && cells[i]!==1 && G[i+1][j]) canW[i]=1;
    if(j<k && F[i][j] && fits(i,clues[j]) && G[Math.min(i+clues[j]+1,n)][j+1]){
      diff[i]++; diff[i+clues[j]]--; if(i+clues[j]<n) canW[i+clues[j]]=1; } }
  const out=cells.slice(); let run=0;
  for(let i=0;i<n;i++){ run+=diff[i]; const cb=run>0, cw=canW[i]===1;
    if(!cb && !cw) return null; if(cb && !cw) out[i]=1; else if(cw && !cb) out[i]=0; }
  return out;
}

class Solver{
  constructor(p, opt={}){ this.p=p; this.opt=Object.assign({probe:false, search:false, branch:'naive', trace:true, maxNodes:200000, maxWork:5e7},opt);
    this.work=0; this.probes=0; this.guesses=0; this.backtracks=0; this.events=[]; this.aborted=false; }
  getLine(g,idx){ const {h,w}=this.p; if(idx<h) return g.slice(idx*w, idx*w+w); const c=idx-h, a=new Array(h); for(let r=0;r<h;r++) a[r]=g[r*w+c]; return a; }
  // propagate on grid g (Int8Array). dirty: set of line idx. Returns false on contradiction. emit: whether to trace.
  propagate(g, dirty, emit){
    const {h,w,rows,cols}=this.p; const inq=new Uint8Array(h+w); const q=[];
    for(const d of dirty){ if(!inq[d]){inq[d]=1;q.push(d);} }
    while(q.length){ const idx=q.shift(); inq[idx]=0; this.work++;
      if(this.work>this.opt.maxWork){ this.aborted=true; return false; }
      const line=this.getLine(g,idx); const res=solveLine(line, idx<h?rows[idx]:cols[idx-h]);
      if(!res){ if(emit) this.ev({t:'bad', line:idx}); return false; }
      const ch=[];
      for(let i=0;i<res.length;i++) if(res[i]!==line[i]){
        const r= idx<h? idx : i, c= idx<h? i : idx-h; g[r*w+c]=res[i]; ch.push(r*w+c, res[i]);
        const other = idx<h ? h+c : r; if(!inq[other]){inq[other]=1;q.push(other);} }
      if(emit && ch.length) this.ev({t:'line', line:idx, ch});
    }
    return true;
  }
  ev(e){ if(this.opt.trace){ e.w=this.work; this.events.push(e);} }
  allLines(){ return Array.from({length:this.p.h+this.p.w},(_,i)=>i); }
  linesOf(cell){ const w=this.p.w; return [Math.floor(cell/w), this.p.h + cell%w]; }
  // probing loop; returns {ok, best} where best is branching cell suggestion
  probeAll(g, emit){
    const N=g.length; let progress=true; let scores=null;
    while(progress){ progress=false; scores=new Float64Array(N).fill(-1);
      for(let cell=0;cell<N;cell++){ if(g[cell]!==-1) continue;
        this.probes++;
        const gb=g.slice(); gb[cell]=1; const okB=this.propagate(gb,this.linesOf(cell),false); if(this.aborted) return {ok:false};
        const gw=g.slice(); gw[cell]=0; const okW=this.propagate(gw,this.linesOf(cell),false); if(this.aborted) return {ok:false};
        if(!okB && !okW){ if(emit) this.ev({t:'probe', cell, res:'both'}); return {ok:false}; }
        if(!okB || !okW){ const v=okB?1:0; const src=okB?gb:gw; const ch=[];
          for(let i=0;i<N;i++) if(g[i]===-1 && src[i]!==-1){ g[i]=src[i]; ch.push(i,src[i]); }
          if(emit) this.ev({t:'probe', cell, res: okB?'whitebad':'blackbad', ch});
          progress=true; continue; }
        let nb=0,nw=0; const ch=[];
        for(let i=0;i<N;i++){ if(g[i]!==-1) continue; if(gb[i]!==-1) nb++; if(gw[i]!==-1) nw++;
          if(gb[i]!==-1 && gb[i]===gw[i]){ g[i]=gb[i]; ch.push(i,gb[i]); } }
        if(ch.length){ if(emit) this.ev({t:'probe', cell, res:'both-ok', ch});
          // propagate the newly fixed cells
          const lines=new Set(); for(let i=0;i<ch.length;i+=2) for(const l of this.linesOf(ch[i])) lines.add(l);
          if(!this.propagate(g,[...lines],emit)) return {ok:false};
          progress=true; continue; }
        scores[cell]= Math.min(nb,nw)*1000 + nb+nw;
      }
    }
    let best=-1,bs=-1; for(let i=0;i<N;i++) if(g[i]===-1 && scores[i]>bs){bs=scores[i];best=i;}
    return {ok:true, best};
  }
  solve(){ const N=this.p.h*this.p.w; const g=new Int8Array(N).fill(-1);
    this.t0=Date.now();
    const res=this.dfs(g,0,true); this.ms=Date.now()-this.t0; this.solution=res; return res; }
  dfs(g, depth, first){
    if(first){ if(!this.propagate(g,this.allLines(),true)) return null; }
    let best=-1;
    if(this.opt.probe){ const r=this.probeAll(g,true); if(!r.ok) return null; best=r.best; }
    if(g.indexOf(-1)<0){ this.ev({t:'done'}); return g; }
    if(!this.opt.search){ this.ev({t:'stuck'}); return 'stuck'; }
    if(this.guesses>=this.opt.maxNodes){ this.aborted=true; return null; }
    let cell = (this.opt.branch==='smart' && best>=0) ? best : g.indexOf(-1);
    const snap=g.slice();
    for(const v of (this.opt.branch==='smart'?[1,0]:[1,0])){
      const g2=snap.slice(); g2[cell]=v; this.guesses++;
      this.ev({t:'guess', cell, v, depth});
      if(this.propagate(g2,this.linesOf(cell),true)){
        const r=this.dfs(g2,depth+1,false); if(r) return r; }
      if(this.aborted) return null;
      this.backtracks++; this.ev({t:'restore', depth, grid: Array.from(snap)});
    }
    return null;
  }
}
// count solutions up to cap (uses probing+search)
function countSolutions(p, cap=2){
  let count=0; const s=new Solver(p,{probe:false,search:true,trace:false});
  function rec(g){ if(count>=cap) return; if(g.indexOf(-1)<0){count++;return;}
    const cell=g.indexOf(-1); for(const v of [1,0]){ const g2=g.slice(); g2[cell]=v; if(s.propagate(g2,s.linesOf(cell),false)) rec(g2); if(count>=cap) return; } }
  const g=new Int8Array(p.h*p.w).fill(-1); if(s.propagate(g,s.allLines(),false)) rec(g); return count;
}
if(typeof module!=='undefined') module.exports={Solver,solveLine,puzzleFromGrid,countSolutions,cluesOf};

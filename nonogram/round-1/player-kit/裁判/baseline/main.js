const { Solver } = require('./solver.js');
const readline = require('readline');

const rl = readline.createInterface({ input: process.stdin, terminal: false });
let head = null, clues = [];

function solveOne(id, h, w, lines) {
  const cl = lines.map(l => l.trim().split(/\s+/).map(Number).filter(x => x > 0));
  const p = { h, w, rows: cl.slice(0, h), cols: cl.slice(h) };
  const s = new Solver(p, { probe: true, search: true, branch: 'smart', trace: false, maxNodes: 1e12, maxWork: 1e15 });
  const g = s.solve();
  if (!g || g === 'stuck') return `UNSOLVED ${id}\n`;
  let out = `SOLUTION ${id}\n`;
  for (let r = 0; r < h; r++) {
    let row = '';
    for (let c = 0; c < w; c++) row += g[r * w + c] ? '#' : '.';
    out += row + '\n';
  }
  return out;
}

rl.on('line', line => {
  if (head === null) {
    const t = line.trim().split(/\s+/);
    if (t[0] === 'PUZZLE') { head = { id: t[1], h: +t[2], w: +t[3] }; clues = []; }
    return;
  }
  clues.push(line);
  if (clues.length === head.h + head.w) {
    process.stdout.write(solveOne(head.id, head.h, head.w, clues));
    head = null;
  }
});

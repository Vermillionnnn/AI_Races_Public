const fs = require('fs');
const path = require('path');
const html = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'index.html'), 'utf8');
// pull out TILE_RE, RULE_KEYS and checkState from the page script
const start = html.indexOf('const TILE_RE');
const end = html.indexOf('function showProblems');
const snippet = html.slice(start, end);
eval(snippet);
const states = JSON.parse(fs.readFileSync(path.join(__dirname, '_states.json'), 'utf8'));
let fail = 0;
for (const [name, st] of states) {
  const problems = checkState(st);
  if (problems.length) { fail++; console.log('[' + name + '] PROBLEMS:\n  ' + problems.join('\n  ')); }
  else console.log('[' + name + '] format OK');
}
process.exit(fail ? 1 : 0);
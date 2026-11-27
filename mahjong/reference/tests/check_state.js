// 用牌桌页面自己的 checkState 检查一批状态（思路同 round-1 的 check_format.js）。
// 用法：node check_state.js 页面.html 状态.json   （状态.json 是 [[名字, 状态], ...]）
// 有问题时逐条打印并以 1 退出。
const fs = require('fs');
const [page, file] = process.argv.slice(2);
const html = fs.readFileSync(page, 'utf8');
const start = html.indexOf('const TILE_RE');
const end = html.indexOf('function showProblems');
if (start < 0 || end < 0) { console.log('页面里找不到 checkState'); process.exit(2); }
eval(html.slice(start, end));
const states = JSON.parse(fs.readFileSync(file, 'utf8'));
let fail = 0;
for (const [name, st] of states) {
  const problems = checkState(st);
  if (problems.length) {
    fail++;
    if (fail <= 20) console.log('[' + name + '] ' + problems.join('；'));
  }
}
console.log('checkState：' + states.length + ' 个状态，' + fail + ' 个有问题');
process.exit(fail ? 1 : 0);

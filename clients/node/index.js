// AI Hub — client Node.js. Không dependency, không cần npm install.
// Dùng:  const aihub = require(require('os').homedir() + '/.aihub/clients/node');
// Đặt AIHUB_HOME nếu hub không nằm ở ~/.aihub.
'use strict';
const { execFileSync } = require('child_process');
const os = require('os');
const path = require('path');

const fs = require('fs');

const HOME = process.env.AIHUB_HOME || path.join(os.homedir(), '.aihub');
const WIN = process.platform === 'win32';

// Trên Windows điểm vào là aihub.cmd, mà Node chỉ chạy được .cmd khi bật
// `shell: true` — lúc đó tham số bị nối chuỗi chứ không escape (Node 24 cảnh báo
// DEP0190). Nên ở đây gọi thẳng Python đúng như .cmd vẫn làm: không shell,
// tham số truyền nguyên vẹn.
function pythonEntry() {
  const venv = path.join(HOME, '.venv', 'Scripts', 'python.exe');
  const exe = fs.existsSync(venv) ? venv : 'python';
  const src = path.join(HOME, 'clients', 'python', 'src');
  return [exe, ['-c',
    'import sys; sys.path.insert(0, ' + JSON.stringify(src) + '); ' +
    'from aihub.cli import main; sys.exit(main())']];
}

const [CMD, PREFIX] = process.env.AIHUB_BIN ? [process.env.AIHUB_BIN, []]
                    : WIN                    ? pythonEntry()
                    : [path.join(HOME, 'bin', 'aihub'), []];

const memo = new Map();
function run(...args) {
  return execFileSync(CMD, PREFIX.concat(args),
                      { encoding: 'utf8', env: process.env, windowsHide: true }).trim();
}

/** Đường dẫn model trên đĩa (không tải). Ném lỗi nếu chưa có. */
function modelPath(name) {
  if (!memo.has(name)) memo.set(name, run('path', name));
  return memo.get(name);
}

/** Tải nếu thiếu rồi trả đường dẫn. */
function ensure(name) {
  const p = run('ensure', name);
  memo.set(name, p);
  return p;
}

/** { base, openai, model, api_key } */
function endpoint(name) {
  return JSON.parse(run('endpoint', '--json', name));
}

/** Danh sách model. opts: { task, runtime, status } */
function list(opts = {}) {
  const args = ['list', '--json'];
  for (const k of ['task', 'runtime', 'status']) {
    if (opts[k]) args.push('--' + k, opts[k]);
  }
  return JSON.parse(run(...args));
}

/** Biến môi trường của hub — trải vào env khi spawn tiến trình con.
 *  Quan trọng với Electron: app mở từ Finder KHÔNG có env của zsh. */
function env() {
  return JSON.parse(run('env', '--json'));
}

module.exports = { path: modelPath, modelPath, ensure, endpoint, list, env };

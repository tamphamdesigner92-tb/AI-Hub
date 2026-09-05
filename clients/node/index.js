// AI Hub — client Node.js. Không dependency, không cần npm install.
// Dùng:  const aihub = require('/Users/mac/.aihub/clients/node');
'use strict';
const { execFileSync } = require('child_process');
const os = require('os');
const path = require('path');

const HOME = process.env.AIHUB_HOME || path.join(os.homedir(), '.aihub');
const BIN = process.env.AIHUB_BIN || path.join(HOME, 'bin', 'aihub');

const memo = new Map();
function run(...args) {
  return execFileSync(BIN, args, { encoding: 'utf8', env: process.env }).trim();
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

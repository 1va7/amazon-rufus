#!/usr/bin/env node
// Amazon Rufus Skill — 环境检查 + CDP Proxy 启动
// 改编自 eze-is/web-access (MIT)，已调整路径引用

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SCRIPTS_DIR = path.dirname(fileURLToPath(import.meta.url));
const PROXY_SCRIPT = path.join(SCRIPTS_DIR, 'cdp-proxy.mjs');
const PROXY_PORT = Number(process.env.CDP_PROXY_PORT || 3456);

function checkNode() {
  const major = Number(process.versions.node.split('.')[0]);
  const version = `v${process.versions.node}`;
  if (major >= 22) {
    console.log(`node: ok (${version})`);
  } else {
    console.warn(`node: warn (${version}, 建议升级到 22+，当前版本可能需要安装 ws 模块)`);
  }
}

function checkPort(port, host = '127.0.0.1', timeoutMs = 2000) {
  return new Promise((resolve) => {
    const socket = net.createConnection(port, host);
    const timer = setTimeout(() => { socket.destroy(); resolve(false); }, timeoutMs);
    socket.once('connect', () => { clearTimeout(timer); socket.destroy(); resolve(true); });
    socket.once('error', () => { clearTimeout(timer); resolve(false); });
  });
}

function activePortFiles() {
  const home = os.homedir();
  const localAppData = process.env.LOCALAPPDATA || '';
  switch (os.platform()) {
    case 'darwin':
      return [
        path.join(home, 'Library/Application Support/Google/Chrome/DevToolsActivePort'),
        path.join(home, 'Library/Application Support/Google/Chrome Canary/DevToolsActivePort'),
        path.join(home, 'Library/Application Support/Chromium/DevToolsActivePort'),
      ];
    case 'linux':
      return [
        path.join(home, '.config/google-chrome/DevToolsActivePort'),
        path.join(home, '.config/chromium/DevToolsActivePort'),
      ];
    case 'win32':
      return [
        path.join(localAppData, 'Google/Chrome/User Data/DevToolsActivePort'),
        path.join(localAppData, 'Chromium/User Data/DevToolsActivePort'),
      ];
    default:
      return [];
  }
}

async function detectChromePort() {
  for (const filePath of activePortFiles()) {
    try {
      const lines = fs.readFileSync(filePath, 'utf8').trim().split(/\r?\n/).filter(Boolean);
      const port = parseInt(lines[0], 10);
      if (port > 0 && port < 65536 && await checkPort(port)) return port;
    } catch (_) {}
  }
  for (const port of [9222, 9229, 9333]) {
    if (await checkPort(port)) return port;
  }
  return null;
}

function httpGetJson(url, timeoutMs = 3000) {
  return fetch(url, { signal: AbortSignal.timeout(timeoutMs) })
    .then(async (res) => { try { return JSON.parse(await res.text()); } catch { return null; } })
    .catch(() => null);
}

function startProxyDetached() {
  const logFile = path.join(os.tmpdir(), 'amazon-rufus-cdp-proxy.log');
  const logFd = fs.openSync(logFile, 'a');
  const child = spawn(process.execPath, [PROXY_SCRIPT], {
    detached: true,
    stdio: ['ignore', logFd, logFd],
    ...(os.platform() === 'win32' ? { windowsHide: true } : {}),
  });
  child.unref();
  fs.closeSync(logFd);
}

async function ensureProxy() {
  const targetsUrl = `http://127.0.0.1:${PROXY_PORT}/targets`;
  const targets = await httpGetJson(targetsUrl);
  if (Array.isArray(targets)) { console.log('proxy: ready'); return true; }

  console.log('proxy: starting...');
  startProxyDetached();
  await new Promise((r) => setTimeout(r, 2000));

  for (let i = 1; i <= 15; i++) {
    const result = await httpGetJson(targetsUrl, 8000);
    if (Array.isArray(result)) { console.log('proxy: ready'); return true; }
    if (i === 1) console.log('⚠️  Chrome 可能弹出授权请求，请点击「允许」后等待...');
    await new Promise((r) => setTimeout(r, 1000));
  }

  console.log('❌ 连接超时');
  console.log(`  日志：${path.join(os.tmpdir(), 'amazon-rufus-cdp-proxy.log')}`);
  return false;
}

async function main() {
  checkNode();
  const chromePort = await detectChromePort();
  if (!chromePort) {
    console.log('chrome: NOT FOUND');
    console.log('');
    console.log('请按以下步骤开启 Chrome 远程调试：');
    console.log('  1. 打开 Google Chrome');
    console.log('  2. 在地址栏输入: chrome://inspect/#remote-debugging');
    console.log('  3. 勾选 "Allow remote debugging for this browser instance"');
    console.log('  4. 重新运行此脚本');
    process.exit(1);
  }
  console.log(`chrome: ok (port ${chromePort})`);

  const ok = await ensureProxy();
  if (!ok) process.exit(1);
}

await main();

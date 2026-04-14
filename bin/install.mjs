#!/usr/bin/env node
/**
 * Amazon Rufus Skill — Installer
 *
 * Installs the skill into Claude Code's plugin directory so it's
 * auto-discovered and available as the `amazon-rufus` skill.
 *
 * Usage:
 *   npx github:1va7/amazon-rufus
 */

import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT  = path.resolve(__dirname, '..');  // parent of bin/

// Target: create our own marketplace entry so we don't depend on web-access
const CLAUDE_DIR        = path.join(os.homedir(), '.claude');
const MARKETPLACE_DIR   = path.join(CLAUDE_DIR, 'plugins', 'marketplaces', 'amazon-rufus');
const SKILL_TARGET      = path.join(MARKETPLACE_DIR, 'plugins', 'amazon-rufus', 'skills', 'amazon-rufus');
const KNOWN_MARKETPLACES = path.join(CLAUDE_DIR, 'plugins', 'known_marketplaces.json');

// Files/dirs to copy from repo root (exclude installer-only files)
const SKIP = new Set(['bin', 'node_modules', '.git', 'package.json', 'package-lock.json', 'README.md', '.npmignore']);

function copyDir(src, dest) {
  fs.mkdirSync(dest, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    if (SKIP.has(entry.name)) continue;
    const srcPath  = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function registerMarketplace() {
  let registry = {};
  try {
    registry = JSON.parse(fs.readFileSync(KNOWN_MARKETPLACES, 'utf8'));
  } catch (_) {}

  registry['amazon-rufus'] = {
    source: { source: 'local', path: MARKETPLACE_DIR },
    installLocation: MARKETPLACE_DIR,
    lastUpdated: new Date().toISOString(),
  };

  fs.mkdirSync(path.dirname(KNOWN_MARKETPLACES), { recursive: true });
  fs.writeFileSync(KNOWN_MARKETPLACES, JSON.stringify(registry, null, 4));
}

function main() {
  console.log('Installing amazon-rufus skill for Claude Code...\n');

  // Copy skill files
  console.log(`  → ${SKILL_TARGET}`);
  copyDir(REPO_ROOT, SKILL_TARGET);
  console.log('  ✓ Skill files copied');

  // Register marketplace
  registerMarketplace();
  console.log('  ✓ Registered in Claude Code plugin registry');

  console.log(`
✅ Installation complete!

Restart Claude Code, then give me an Amazon ASIN to get started:
  "帮我 scrape 这个产品的 Rufus FAQ，ASIN: B0DN9WR2TX"

First run will guide you through:
  1. Enabling Chrome remote debugging (one-time)
  2. Creating a Feishu app + Bitable (one-time)

Skill location: ${SKILL_TARGET}
`);
}

main();

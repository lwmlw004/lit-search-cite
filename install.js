#!/usr/bin/env node
/**
 * lit-search-cite — One-command skill installer.
 *
 * Detects available AI coding platforms and copies the skill to the
 * appropriate directory. User can also specify a target with flags.
 *
 * Usage:
 *   npx lit-search-cite                    # auto-detect + install
 *   npx lit-search-cite --claude           # Claude Code only
 *   npx lit-search-cite --opencode         # OpenCode only
 *   npx lit-search-cite --target ~/skills  # custom path
 */

const fs = require("fs");
const path = require("path");
const os = require("os");

const SKILL_NAME = "lit-search-cite";
const SRC = path.resolve(__dirname);

// Platform-specific skill directories
const TARGETS = {
  claude: {
    label: "Claude Code",
    dirs: [
      path.join(os.homedir(), ".claude", "skills", SKILL_NAME),           // personal
      path.join(process.cwd(), ".claude", "skills", SKILL_NAME),          // project
    ],
  },
  opencode: {
    label: "OpenCode / Codex",
    dirs: [
      path.join(os.homedir(), ".config", "opencode", "skills", SKILL_NAME),
      path.join(process.cwd(), ".opencode", "skills", SKILL_NAME),
    ],
  },
  agents: {
    label: "Agent Skills (universal)",
    dirs: [
      path.join(os.homedir(), ".agents", "skills", SKILL_NAME),
      path.join(process.cwd(), ".agents", "skills", SKILL_NAME),
    ],
  },
};

function copyDir(src, dest) {
  if (!fs.existsSync(dest)) {
    fs.mkdirSync(dest, { recursive: true });
  }
  const entries = fs.readdirSync(src, { withFileTypes: true });
  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "node_modules" || entry.name === ".git") continue;
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }
}

function install(targetKey) {
  const target = TARGETS[targetKey];
  if (!target) {
    console.error(`Unknown target: ${targetKey}`);
    return false;
  }

  const dest = target.dirs.find(d => {
    try { fs.mkdirSync(path.dirname(d), { recursive: true }); return true; }
    catch { return false; }
  });

  if (!dest) {
    console.log(`  ${target.label}: skipped (no writable directory)`);
    return false;
  }

  console.log(`  ${target.label}: ${dest}`);
  copyDir(SRC, dest);
  return true;
}

// ── Main ──────────────────────────────────────────────────────────────────────
const args = process.argv.slice(2);
const flags = {
  claude: args.includes("--claude") || args.includes("-c"),
  opencode: args.includes("--opencode") || args.includes("-o"),
  agents: args.includes("--agents") || args.includes("-a"),
  all: args.includes("--all"),
};

// If --target is specified, install to that path
const targetIdx = args.indexOf("--target");
if (targetIdx >= 0 && args[targetIdx + 1]) {
  const dest = args[targetIdx + 1];
  console.log(`\n  lit-search-cite v${require("./package.json").version}`);
  console.log(`  Installing to: ${dest}\n`);
  copyDir(SRC, dest);
  console.log("  Done.\n");
  process.exit(0);
}

const anyFlag = flags.claude || flags.opencode || flags.agents || flags.all;
const toInstall = anyFlag
  ? Object.keys(flags).filter(k => flags[k] && k !== "all")
  : Object.keys(TARGETS); // auto-detect all

console.log(`\n  lit-search-cite v${require("./package.json").version}`);
console.log(`  Installing skill...\n`);

let installed = 0;
for (const key of toInstall) {
  if (install(key)) installed++;
}

console.log(`\n  Done — installed to ${installed} location(s).`);
console.log(`  Run 'npx lit-search-cite --help' for options.\n`);

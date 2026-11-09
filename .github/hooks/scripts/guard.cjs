#!/usr/bin/env node
'use strict';
// Guard for agent tool calls. Denies unsafe actions; returns {} to allow.
// Fails closed: any parse error denies the tool call.

const fs = require('node:fs');
const path = require('node:path');

const PROTECTED_PATHS = [
  '.github/agents', '.github/skills', '.github/hooks', '.github/workflows',
  '.github/factory', '.github/AGENTS.md', '.github/copilot-instructions.md', '.github/CODEOWNERS',
];
const SECRET_PATTERN = /(\.env(\.[a-z]+)?\b|id_rsa|\.pem\b|credentials\.json|service[-_]account[^"\s]*\.json|\bsecrets?\/)/i;
const DESTRUCTIVE_PATTERN = /\brm\s+-rf?\b|git\s+push\b[^\n]*--force|git\s+push\b[^\n]*\s(main|master)\b|terraform\s+destroy|gcloud\b[^\n]*\bdelete\b|DROP\s+(TABLE|DATABASE)/i;
const WRITE_TOOL = /edit|write|create|replace|patch/i;
const SHELL_TOOL = /terminal|shell|bash|exec|run/i;
const AUDIT_LOG = path.join(__dirname, 'audit.log');

function deny(reason) {
  return { permissionDecision: 'deny', permissionDecisionReason: reason };
}

function audit(toolName, decision) {
  const line = `${new Date().toISOString()} ${toolName} ${decision}\n`;
  try {
    fs.appendFileSync(AUDIT_LOG, line);
  } catch {
    // Audit failure must not change the decision.
  }
}

function decide(event) {
  const toolName = String(event.toolName ?? '');
  const args = typeof event.toolArgs === 'string' ? event.toolArgs : JSON.stringify(event.toolArgs ?? {});

  if (WRITE_TOOL.test(toolName)) {
    const hit = PROTECTED_PATHS.find((p) => args.includes(p));
    if (hit) return deny(`Agents may not modify ${hit}. A human owner must change factory configuration.`);
  }

  if (SECRET_PATTERN.test(args)) {
    return deny('Access to secret or credential files is not allowed. Use runner secrets only.');
  }

  if (SHELL_TOOL.test(toolName) && DESTRUCTIVE_PATTERN.test(args)) {
    return deny('Destructive command blocked. Ask a human to run it.');
  }

  return {};
}

let input = '';
process.stdin.on('data', (chunk) => (input += chunk));
process.stdin.on('end', () => {
  let output;
  let toolName = 'unknown';
  try {
    const event = JSON.parse(input);
    toolName = String(event.toolName ?? 'unknown');
    output = decide(event);
  } catch (err) {
    output = deny(`Guard could not parse the tool call: ${err.message}`);
  }
  audit(toolName, output.permissionDecision ?? 'allow');
  process.stdout.write(JSON.stringify(output));
});

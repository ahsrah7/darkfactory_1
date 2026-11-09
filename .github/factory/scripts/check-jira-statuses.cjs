#!/usr/bin/env node
'use strict';
// Checks that every state name in state-machine.json exists as a Jira status. Exits 1 if any are missing.

const fs = require('node:fs');
const path = require('node:path');

const machine = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'state-machine.json'), 'utf8'));
const env = process.env;

const wanted = new Set();
for (const t of machine.transitions) {
  for (const [key, value] of Object.entries(t)) {
    if (key === 'from' || (key.startsWith('on') && typeof value === 'string')) wanted.add(value);
  }
}
wanted.delete('previous status');

async function main() {
  for (const name of ['JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN', 'JIRA_PROJECT_KEY']) {
    if (!env[name]) throw new Error(`Missing env: ${name}`);
  }

  const auth = Buffer.from(`${env.JIRA_EMAIL}:${env.JIRA_API_TOKEN}`).toString('base64');
  const base = env.JIRA_BASE_URL.replace(/\/$/, '');
  const res = await fetch(`${base}/rest/api/3/project/${env.JIRA_PROJECT_KEY}/statuses`, {
    headers: { Authorization: `Basic ${auth}`, Accept: 'application/json' },
  });
  if (!res.ok) throw new Error(`Jira statuses failed: ${res.status} ${await res.text()}`);

  const issueTypes = await res.json();
  const available = new Set(issueTypes.flatMap((it) => it.statuses.map((s) => s.name)));
  const missing = [...wanted].filter((name) => !available.has(name));

  console.log(`Checked ${wanted.size} state names against ${available.size} Jira statuses.`);
  if (missing.length) {
    console.error(`Missing in Jira (names are case-sensitive): ${missing.join(', ')}`);
    for (const it of issueTypes) console.error(`${it.name}: ${it.statuses.map((s) => s.name).join(', ')}`);
    process.exit(1);
  }
  console.log('All state names exist in Jira.');
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});

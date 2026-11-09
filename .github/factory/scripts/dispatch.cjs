#!/usr/bin/env node
'use strict';
// Queues Jira work and assigns coding agents through Copilot cloud agent. Dry run unless DISPATCH_ENABLED=true.

const fs = require('node:fs');
const path = require('node:path');

const factoryDir = path.resolve(__dirname, '..');
const config = JSON.parse(fs.readFileSync(path.join(factoryDir, 'config.json'), 'utf8'));
const machine = JSON.parse(fs.readFileSync(path.join(factoryDir, 'state-machine.json'), 'utf8'));

const env = process.env;
const dispatchEnabled = env.DISPATCH_ENABLED === 'true';
const jiraBase = (env.JIRA_BASE_URL || '').replace(/\/$/, '');
const ROUTED = 'routed';

function requireEnv(names) {
  const missing = names.filter((n) => !env[n]);
  if (missing.length) throw new Error(`Missing env: ${missing.join(', ')}`);
}

async function jira(pathname, options = {}) {
  const auth = Buffer.from(`${env.JIRA_EMAIL}:${env.JIRA_API_TOKEN}`).toString('base64');
  const res = await fetch(`${jiraBase}${pathname}`, {
    ...options,
    headers: { Authorization: `Basic ${auth}`, Accept: 'application/json', 'Content-Type': 'application/json' },
  });
  if (!res.ok) throw new Error(`Jira ${pathname} failed: ${res.status} ${await res.text()}`);
  return res.json();
}

async function github(pathname, options = {}) {
  const res = await fetch(`https://api.github.com${pathname}`, {
    ...options,
    headers: {
      Authorization: `Bearer ${env.GH_PAT}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'Content-Type': 'application/json',
    },
  });
  if (!res.ok) throw new Error(`GitHub ${pathname} failed: ${res.status} ${await res.text()}`);
  return res.json();
}

// Jira descriptions are Atlassian Document Format; flatten to plain text.
function adfToText(node) {
  if (!node) return '';
  if (typeof node.text === 'string') return node.text;
  const inner = (node.content || []).map(adfToText).join('');
  const block = ['paragraph', 'heading', 'listItem', 'codeBlock'].includes(node.type);
  return block ? `${inner}\n` : inner;
}

function budgetCapUsd() {
  const { creditBalanceUsd, allocationPercent } = config.budget;
  if (typeof creditBalanceUsd !== 'number') return null;
  return (creditBalanceUsd * allocationPercent) / 100;
}

function resolveAgent(transition, labels) {
  if (transition.agent !== ROUTED) return transition.agent;
  const match = Object.entries(config.levels.labels).find(([label]) => labels.includes(label));
  return match ? match[1] : config.levels.default;
}

async function assignToCopilot(issue, agent) {
  const key = issue.key;
  const query = `repo:${env.GITHUB_REPOSITORY} is:issue in:title "[${key}]"`;
  const existing = await github(`/search/issues?q=${encodeURIComponent(query)}`);
  if (existing.total_count > 0) return `already assigned #${existing.items[0].number}`;

  const created = await github(`/repos/${env.GITHUB_REPOSITORY}/issues`, {
    method: 'POST',
    body: JSON.stringify({
      title: `[${key}] ${issue.fields.summary}`,
      body: `Jira: ${jiraBase}/browse/${key}\n\n${adfToText(issue.fields.description)}`,
      assignees: ['copilot-swe-agent[bot]'],
      agent_assignment: {
        target_repo: env.GITHUB_REPOSITORY,
        base_branch: 'main',
        custom_instructions: '',
        custom_agent: agent,
        model: '',
      },
    }),
  });
  return `assigned #${created.number}`;
}

async function main() {
  requireEnv(['JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN', 'JIRA_PROJECT_KEY']);
  if (!config.factory.enabled) {
    console.log('Factory disabled in config.json. No work queued.');
    return;
  }

  const cap = budgetCapUsd();
  const spent = Number(env.BUDGET_SPENT_USD);
  const budgetOk = cap !== null && Number.isFinite(spent) && spent < cap;
  if (dispatchEnabled) {
    requireEnv(['GH_PAT', 'GITHUB_REPOSITORY']);
    if (!budgetOk) console.warn('Budget not confirmed. Set budget.creditBalanceUsd and BUDGET_SPENT_USD. Assignments blocked.');
  }

  const limit = config.factory.maxParallelAgents;
  const rows = [];

  for (const t of machine.transitions) {
    if (rows.length >= limit) break;
    if (!t.agent) continue;

    const jql = `project = "${env.JIRA_PROJECT_KEY}" AND status = "${t.from}" ORDER BY priority DESC, created ASC`;
    const data = await jira('/rest/api/3/search/jql', {
      method: 'POST',
      body: JSON.stringify({ jql, maxResults: limit - rows.length, fields: ['summary', 'labels', 'description'] }),
    });

    for (const issue of data.issues || []) {
      const agent = resolveAgent(t, issue.fields.labels || []);
      if (!config.agents[agent]?.enabled) continue;

      let outcome = 'queued (no backend)';
      if (config.copilotAgents.includes(agent)) {
        if (!dispatchEnabled) outcome = 'dry run';
        else if (!budgetOk) outcome = 'blocked: budget';
        else outcome = await assignToCopilot(issue, agent);
      }
      const summary = (issue.fields.summary || '').replace(/\|/g, '/');
      rows.push(`| ${issue.key} | ${t.from} | ${agent} | ${outcome} | ${summary} |`);
    }
  }

  const report = [
    '## Factory queue',
    '',
    `Dispatch: ${dispatchEnabled ? 'enabled' : 'dry run'}. Budget cap: ${cap === null ? 'not set' : `$${cap.toFixed(2)}`}.`,
    '',
    '| Key | Status | Agent | Outcome | Summary |',
    '|---|---|---|---|---|',
    ...rows,
    '',
  ].join('\n');

  console.log(report);
  if (env.GITHUB_STEP_SUMMARY) {
    fs.appendFileSync(env.GITHUB_STEP_SUMMARY, report + '\n');
  }
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});

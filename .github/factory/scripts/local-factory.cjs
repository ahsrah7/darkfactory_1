#!/usr/bin/env node
'use strict';
// Local runner: polls Jira, runs Copilot CLI agents in git worktrees, pushes branches and opens PRs. Dry run unless LOCAL_FACTORY_RUN=true.

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const factoryDir = path.resolve(__dirname, '..');
const repoRoot = path.resolve(factoryDir, '..', '..');
const config = JSON.parse(fs.readFileSync(path.join(factoryDir, 'config.json'), 'utf8'));
const machine = JSON.parse(fs.readFileSync(path.join(factoryDir, 'state-machine.json'), 'utf8'));
const stateDir = path.join(factoryDir, 'state');
const runsFile = path.join(stateDir, 'runs.json');
const worktreeRoot = path.join(path.dirname(repoRoot), `${path.basename(repoRoot)}-worktrees`);

const env = process.env;
const runEnabled = env.LOCAL_FACTORY_RUN === 'true';
const jiraBase = (env.JIRA_BASE_URL || '').replace(/\/$/, '');
const local = config.localRunner;
const ROUTED = 'routed';

function log(msg) {
  console.log(`[${new Date().toISOString()}] ${msg}`);
}

function requireEnv(names) {
  const missing = names.filter((n) => !env[n]);
  if (missing.length) throw new Error(`Missing env: ${missing.join(', ')}`);
}

function sh(cmd, args, options = {}) {
  const res = spawnSync(cmd, args, { encoding: 'utf8', ...options });
  if (res.error) throw res.error;
  return res;
}

function git(args, cwd = repoRoot) {
  const res = sh('git', args, { cwd });
  if (res.status !== 0) throw new Error(`git ${args.join(' ')} failed: ${res.stderr.trim()}`);
  return res.stdout.trim();
}

function githubRepo() {
  const url = git(['remote', 'get-url', 'origin']);
  const m = url.match(/github\.com[:/](.+?)(\.git)?$/);
  if (!m) throw new Error(`Cannot read GitHub repo from origin: ${url}`);
  return m[1];
}

function loadRuns() {
  return fs.existsSync(runsFile) ? JSON.parse(fs.readFileSync(runsFile, 'utf8')) : {};
}

function saveRuns(runs) {
  fs.mkdirSync(stateDir, { recursive: true });
  fs.writeFileSync(runsFile, JSON.stringify(runs, null, 2));
}

async function jira(pathname, options = {}) {
  const auth = Buffer.from(`${env.JIRA_EMAIL}:${env.JIRA_API_TOKEN}`).toString('base64');
  const res = await fetch(`${jiraBase}${pathname}`, {
    ...options,
    headers: { Authorization: `Basic ${auth}`, Accept: 'application/json', 'Content-Type': 'application/json' },
  });
  if (!res.ok) throw new Error(`Jira ${pathname} failed: ${res.status} ${await res.text()}`);
  return res.status === 204 ? null : res.json();
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

function textComment(text) {
  return { body: { type: 'doc', version: 1, content: [{ type: 'paragraph', content: [{ type: 'text', text }] }] } };
}

async function transition(key, toName) {
  const data = await jira(`/rest/api/3/issue/${key}/transitions`);
  const match = data.transitions.find((t) => t.to.name === toName);
  if (!match) throw new Error(`No Jira transition to "${toName}" available for ${key}`);
  await jira(`/rest/api/3/issue/${key}/transitions`, {
    method: 'POST',
    body: JSON.stringify({ transition: { id: match.id } }),
  });
}

function resolveAgent(transition, labels) {
  if (transition.agent !== ROUTED) return transition.agent;
  const match = Object.entries(config.levels.labels).find(([label]) => labels.includes(label));
  return match ? match[1] : config.levels.default;
}

function slugify(text) {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40);
}

function buildPrompt(issue, agent) {
  return [
    `Work on Jira ticket ${issue.key}: ${issue.fields.summary}`,
    '',
    adfToText(issue.fields.description).trim(),
    '',
    `Follow the ${agent} agent instructions. Commit your work on the current branch with a clear message.`,
    'Do not push and do not open a pull request; the local factory does that.',
    'Never change files under .github/.',
  ].join('\n');
}

function runCopilot(cwd, agent, prompt) {
  const perms = local.permissionMode === 'allow-all'
    ? ['--allow-all-tools']
    : [`--allow-tool=${local.allowedTools.join(',')}`];
  const args = ['-p', prompt, `--agent=${agent}`, '--no-ask-user', '--deny-tool=shell(git push)', ...perms];
  return sh(local.copilotCommand, args, {
    cwd,
    env: { ...env, GITHUB_COPILOT_PROMPT_MODE_REPO_HOOKS: 'true' },
    timeout: local.agentTimeoutMinutes * 60 * 1000,
    maxBuffer: 64 * 1024 * 1024,
  });
}

async function runOne(issue, agent, t, runs) {
  const key = issue.key;
  const branch = `${key}/${slugify(issue.fields.summary)}`;
  const wt = path.join(worktreeRoot, key);
  const record = { agent, branch, worktree: wt, status: 'running', startedAt: new Date().toISOString() };
  runs[key] = record;
  saveRuns(runs);

  try {
    git(['fetch', 'origin', 'main']);
    if (!fs.existsSync(wt)) {
      fs.mkdirSync(worktreeRoot, { recursive: true });
      git(['worktree', 'add', '-B', branch, wt, 'origin/main']);
    }

    const res = runCopilot(wt, agent, buildPrompt(issue, agent));
    if (res.status !== 0) throw new Error(`agent exited ${res.status}: ${(res.stderr || res.stdout || '').slice(-800)}`);

    if (git(['status', '--porcelain'], wt)) {
      git(['add', '-A'], wt);
      git(['commit', '-m', `${key}: ${issue.fields.summary}`], wt);
    }
    if (!git(['rev-list', `origin/main..${branch}`], wt)) throw new Error('agent produced no commits');

    git(['push', '-u', 'origin', branch], wt);
    const pr = await github(`/repos/${githubRepo()}/pulls`, {
      method: 'POST',
      body: JSON.stringify({
        title: `[${key}] ${issue.fields.summary}`,
        head: branch,
        base: 'main',
        body: `Jira: ${jiraBase}/browse/${key}\nAgent: ${agent}\nOpened by the local factory.`,
      }),
    });
    record.status = 'done';
    record.prUrl = pr.html_url;
    if (t.onSuccess) await transition(key, t.onSuccess);
    log(`${key}: PR ${pr.html_url}`);
  } catch (err) {
    record.status = 'failed';
    record.error = err.message.slice(0, 500);
    if (t.onBlocked) await transition(key, t.onBlocked).catch(() => {});
    await jira(`/rest/api/3/issue/${key}/comment`, {
      method: 'POST',
      body: JSON.stringify(textComment(`Local factory run failed for ${agent}: ${record.error}`)),
    }).catch(() => {});
    log(`${key}: failed: ${record.error}`);
  } finally {
    saveRuns(runs);
  }
}

async function main() {
  requireEnv(['JIRA_BASE_URL', 'JIRA_EMAIL', 'JIRA_API_TOKEN', 'JIRA_PROJECT_KEY']);
  if (!config.factory.enabled) {
    log('Factory disabled in config.json.');
    return;
  }

  const runs = loadRuns();
  const limit = config.factory.maxParallelAgents;
  let queued = 0;

  for (const t of machine.transitions) {
    if (!t.agent || queued >= limit) continue;
    const data = await jira('/rest/api/3/search/jql', {
      method: 'POST',
      body: JSON.stringify({
        jql: `project = "${env.JIRA_PROJECT_KEY}" AND status = "${t.from}" ORDER BY priority DESC, created ASC`,
        maxResults: limit - queued,
        fields: ['summary', 'labels', 'description'],
      }),
    });

    for (const issue of data.issues || []) {
      const agent = resolveAgent(t, issue.fields.labels || []);
      if (!config.agents[agent]?.enabled || !config.copilotAgents.includes(agent)) continue;
      const prior = runs[issue.key];
      if (prior && ['running', 'failed'].includes(prior.status)) continue;

      queued += 1;
      if (!runEnabled) {
        log(`dry run: ${issue.key} (${t.from}) -> ${agent}`);
        continue;
      }
      await runOne(issue, agent, t, runs);
    }
  }

  log(`${runEnabled ? 'ran' : 'would run'} ${queued} agent job(s)`);
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});

// This client runs on your laptop or server. Generated Python runs only inside Render.
// Node's built-in modules provide files, hashes, paths, argument parsing and timed waits.
import { readFileSync, writeFileSync, mkdirSync, renameSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { join, resolve } from 'node:path';
import { createHash, randomUUID } from 'node:crypto';
import { parseArgs } from 'node:util';
import { setTimeout as sleep } from 'node:timers/promises';
import { Render } from '@renderinc/sdk';

// Both clients read the same task, input cases and trusted remote helper.
const ROOT = fileURLToPath(new URL('../', import.meta.url));
const shared = (name: string) => readFileSync(join(ROOT, 'shared', name), 'utf8');
const contract = JSON.parse(shared('contract.json')) as {
  model: string; max_attempts: number; max_tokens: number; max_source_bytes: number;
  search_query: string; search_domains: string[]; search_results: number; system: string; task: string;
};
type ObjectData = Record<string, unknown>;
type Case = { name: string; input: ObjectData; expected?: ObjectData; expected_error?: boolean };
const cases = JSON.parse(shared('cases.json')) as { public: Case[]; held_out: Case[] };
const remote = Buffer.from(shared('remote.py')).toString('base64');
const driver = shared('driver.py');
type API = Render['experimental']['sandboxes'];
type RemoteResult = { stdout?: string; stderr?: string; exit_code?: number; limit?: string | null; polars?: string; credentials_absent?: boolean };
type Check = { name: string; passed: boolean; actual: ObjectData; exit_code?: number; limit?: string | null };
type Evidence = { url: string; title: string; text: string };
type Search = { request_id?: string; seconds: number; cost_usd?: number; results: Evidence[] };
type Message = { role: string; content: string };
type Call = { id?: string; model?: string; usage?: { cost?: number; [key: string]: unknown }; seconds: number; finish_reason?: string };
type Attempt = { call: Call; source?: string; explanation?: string; source_sha256?: string; public_checks?: Check[]; error?: string };
type Trial = { mode: string; repetition: number; attempts: Attempt[]; passed: boolean; initial?: Check[]; search?: Search | null;
  repair_sandbox?: string; verification_sandbox?: string; candidate_file?: string; source_sha256?: string; verification?: Check[];
  seconds?: number; model_cost_usd?: number; model_cost_complete?: boolean };
type State = { language: string; started_at: string; workspace: string; model: string; complete: boolean;
  sandboxes: { id: string; terminated: boolean; bootstrap: boolean; final_status?: string }[];
  snapshots: { id: string; group: string; deleted: boolean }[]; trials: Trial[];
  fixture_sha256: string; contract_sha256: string; source_sha256?: Record<string, string>; model_requests?: number; pending_create?: ObjectData; pending_snapshot?: string;
  installation?: ObjectData; environment?: RemoteResult; fixture_reference?: Check[];
  network_host_control?: number; network_observation?: RemoteResult;
  boundary_checks?: Record<string, boolean>; fixture_initial?: Check[]; integration_search?: Search; model_preflight?: string;
  cleanup_verified?: boolean; cleanup_errors?: string[]; failure?: string };

// Only these authored errors are printed; raw provider bodies might contain sensitive text.
export class DemoError extends Error { override name = 'DemoError'; }
export const digest = (text: string) => createHash('sha256').update(text).digest('hex');
const quote = (text: string) => "'" + text.replaceAll("'", "'\\''") + "'";

export function parseCandidate(text: string): { source: string; explanation: string } {
  // JSON is data. Parsing it never executes the generated source on this computer.
  const candidate = JSON.parse(text);
  if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate) ||
      Object.keys(candidate).sort().join(',') !== 'explanation,source' ||
      typeof candidate.source !== 'string' || !candidate.source.trim() || typeof candidate.explanation !== 'string' ||
      Buffer.byteLength(candidate.source) > contract.max_source_bytes) throw new DemoError('Invalid candidate JSON or source size');
  return candidate;
}

function canonical(value: unknown): string {
  // Object-key order is irrelevant to JSON equality, but list order must be preserved.
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value !== null && typeof value === 'object') return '{' + Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([k, v]) => JSON.stringify(k) + ':' + canonical(v)).join(',') + '}';
  return JSON.stringify(value);
}

export function judge(test: Case, result: RemoteResult): Check {
  // An exit code alone cannot pass a test: output must match the host-owned expectation.
  let actual: ObjectData;
  try { actual = JSON.parse(result.stdout ?? ''); } catch { actual = { error: 'InvalidOutput' }; }
  const passed = result.exit_code === 0 && !result.limit &&
    (test.expected_error ? actual?.error === 'InvalidOperationError' : canonical(actual) === canonical(test.expected));
  return { name: test.name, passed: Boolean(passed), actual, exit_code: result.exit_code, limit: result.limit };
}

export function makeMessages(source: string, observed: Check[], evidence: Evidence[] | null): Message[] {
  // Held-out inputs and the reference solution are intentionally excluded from model requests.
  const request: ObjectData = { task: contract.task, source, public_cases: cases.public, initial_failures: observed };
  if (evidence !== null) request.retrieved_documentation = evidence;
  return [{ role: 'system', content: contract.system }, { role: 'user', content: JSON.stringify(request) }];
}

export class Run {
  state: State;
  constructor(public api: API, public output: string, model: string) {
    mkdirSync(output, { recursive: false });
    this.state = { language: 'typescript', started_at: new Date().toISOString(), workspace: process.env.RENDER_WORKSPACE_ID!, model,
      sandboxes: [], snapshots: [], trials: [], complete: false, fixture_sha256: digest(shared('cases.json')), contract_sha256: digest(shared('contract.json')), source_sha256: Object.fromEntries(
        ['typescript/main.ts', ...['remote.py', 'driver.py', 'starter.py', 'reference.py', 'cases.json', 'contract.json'].map(name => 'shared/' + name)]
          .map(name => [name, digest(readFileSync(join(ROOT, name), 'utf8'))])) };
    this.save();
  }
  save() {
    // Atomic replacement keeps the recovery journal readable after an interrupted write.
    writeFileSync(join(this.output, 'run.json.tmp'), JSON.stringify(this.state, null, 2) + '\n');
    renameSync(join(this.output, 'run.json.tmp'), join(this.output, 'run.json'));
  }
  async get(sid: string): Promise<{ status: string; networkPolicy: { type?: string; default?: string; rules?: unknown } }> {
    const response = await fetch('https://api.render.com/v1/sandboxes/' + sid,
      { headers: { Authorization: 'Bearer ' + process.env.RENDER_API_KEY }, signal: AbortSignal.timeout(20_000) });
    if (!response.ok) throw new DemoError('Sandbox read returned HTTP ' + response.status);
    return response.json();
  }
  async create(snapshotId?: string, bootstrap = false) {
    // Only trusted package installation may reach PyPI. Every code-execution copy denies outbound networking.
    const policy = bootstrap ? { type: 'allow-list', rules: ['pypi.org', 'files.pythonhosted.org'].map(domain => ({ domain, protocol: 'https' })) } : { type: 'deny-all' };
    this.state.pending_create = { time: new Date().toISOString(), policy }; this.save();
    let sid: string;
    if (bootstrap) {
      const response = await fetch('https://api.render.com/v1/sandboxes', { method: 'POST',
        headers: { Authorization: 'Bearer ' + process.env.RENDER_API_KEY, 'Content-Type': 'application/json' },
        body: JSON.stringify({ ownerId: this.state.workspace, plan: 'starter', timeoutSeconds: 600, networkPolicy: policy }), signal: AbortSignal.timeout(40_000) });
      if (!response.ok) {
        if (response.status < 500) { delete this.state.pending_create; this.save(); }
        throw new DemoError('Sandbox create returned HTTP ' + response.status);
      }
      sid = ((await response.json()) as { id: string }).id;
    } else sid = (await this.api.create({ plan: 'starter', timeoutSeconds: 600, networkPolicy: { default: 'deny-all' }, ...(snapshotId ? { snapshotId } : {}) })).id;
    this.state.sandboxes.push({ id: sid, terminated: false, bootstrap }); delete this.state.pending_create; this.save();
    for (let n = 0; n < 30; n++) {
      const state = await this.get(sid);
      if (state.status === 'running') {
        if ((state.networkPolicy.type ?? state.networkPolicy.default) !== policy.type ||
            (bootstrap && canonical(state.networkPolicy.rules) !== canonical(policy.rules))) throw new DemoError('Effective network policy differs from requested policy');
        return sid;
      }
      if (!['creating', 'pending', 'resuming'].includes(state.status)) throw new DemoError('Sandbox did not reach running');
      await sleep(1000);
    }
    throw new DemoError('Sandbox readiness deadline exceeded');
  }
  async command(sid: string, command: string, seconds = 40) {
    // Stopping the output stream does not stop remote code; final cleanup always terminates its machine.
    const chunks: string[] = []; let size = 0; let exitCode: number | undefined;
    for await (const event of await this.api.exec(sid, command, undefined, AbortSignal.timeout(seconds * 1000))) {
      if (event.type === 'output') {
        size += Buffer.byteLength(event.data);
        if (size > 131072) throw new DemoError('Sandbox output exceeded its limit');
        chunks.push(event.data);
      } else exitCode = event.exit_code;
    }
    if (exitCode === undefined) throw new DemoError('Sandbox stream ended without an exit event');
    return { exit_code: exitCode, output: chunks.join('') };
  }
  async rpc(sid: string, payload: ObjectData): Promise<RemoteResult> {
    // Base64 and shell quoting keep model-authored source inside data, never in command syntax.
    const encoded = Buffer.from(JSON.stringify(payload)).toString('base64');
    const command = ['/opt/demo/bin/python', '-I', '-c', `import base64;exec(base64.b64decode('${remote}'))`, encoded].map(quote).join(' ');
    const result = await this.command(sid, command);
    if (result.exit_code !== 0) throw new DemoError('Remote helper failed');
    return JSON.parse(result.output);
  }
  async checks(sid: string, tests: Case[]) {
    const results: Check[] = [];
    for (const test of tests) results.push(judge(test, await this.rpc(sid, { op: 'check', driver, case: test.input })));
    return results;
  }
  async terminate(sid: string) {
    // Never terminate a sandbox unless its ID is in this run's ownership journal.
    const record = this.state.sandboxes.find(r => r.id === sid);
    if (!record) throw new DemoError('Sandbox is not owned by this run');
    if (record.terminated) return;
    for (let n = 0; n < 3; n++) {
      try { await this.api.terminate(sid); } catch { /* Resolve a lost reply by reading cloud state. */ }
      try {
        const state = await this.get(sid);
        if (state.status === 'terminated') { record.terminated = true; record.final_status = state.status; this.save(); return; }
      } catch { /* Preserve the ID and retry this same cleanup operation only. */ }
      await sleep((n + 1) * 1000);
    }
    throw new DemoError('Cleanup unconfirmed for ' + sid);
  }
  async prepare() {
    const sid = await this.create(undefined, true);
    const result = await this.command(sid, 'python3 -m venv /opt/demo && /opt/demo/bin/pip install --disable-pip-version-check --no-cache-dir polars==2.0.0', 150);
    this.state.installation = result; this.save();
    if (result.exit_code) throw new DemoError('Pinned Polars installation failed');
    // The snapshot contains only the package installation, never generated code or keys.
    this.state.pending_snapshot = sid; this.save();
    const snap = await this.api.snapshots.create({ sandboxId: sid, kind: 'filesystem', name: 'exa-' + this.output.split('/').at(-1), expiresAt: new Date(Date.now() + 3600000).toISOString() });
    const record = { id: snap.id, group: snap.sandboxGroupId, deleted: false };
    this.state.snapshots.push(record); delete this.state.pending_snapshot; this.save();
    for (let n = 0; n < 60; n++) {
      const current = await this.api.snapshots.get({ sandboxGroupId: record.group, snapshotId: record.id });
      if (current.status === 'available') { await this.terminate(sid); return record.id; }
      if (current.status === 'failed') throw new DemoError('Prepared snapshot failed');
      await sleep(1000);
    }
    throw new DemoError('Snapshot readiness deadline exceeded');
  }
  async search(): Promise<Search> {
    const started = performance.now();
    const response = await fetch('https://api.exa.ai/search', { method: 'POST',
      headers: { 'x-api-key': process.env.EXA_API_KEY!, 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: contract.search_query, type: 'auto', numResults: contract.search_results,
        includeDomains: contract.search_domains, contents: { text: { maxCharacters: 14000 } } }), signal: AbortSignal.timeout(60_000) });
    if (!response.ok) throw new DemoError('Exa returned HTTP ' + response.status);
    const body = await response.json() as { requestId?: string; costDollars?: { total: number }; results?: { url: string; title?: string; text?: string }[] };
    const evidence = (body.results ?? []).map(row => ({ url: row.url, title: row.title ?? '', text: (row.text ?? '').slice(0, 14000) })).filter(row => {
      try { const url = new URL(row.url); return url.protocol === 'https:' && contract.search_domains.includes(url.hostname); } catch { return false; }
    });
    if (!evidence.some(row => row.text.trim())) throw new DemoError('Exa returned no readable evidence; search mode cannot proceed');
    return { request_id: body.requestId, seconds: (performance.now() - started) / 1000, cost_usd: body.costDollars?.total, results: evidence };
  }
  async preflightModel() {
    // Check account credit, key limits and model settings before creating a paid machine.
    const headers = { Authorization: 'Bearer ' + process.env.OPENROUTER_API_KEY };
    const credits = await fetch('https://openrouter.ai/api/v1/credits', { headers, signal: AbortSignal.timeout(25_000) });
    if (!credits.ok) throw new DemoError('Could not verify OpenRouter credit');
    const funds = (await credits.json()).data;
    if (funds.total_credits <= funds.total_usage) throw new DemoError('OpenRouter has no remaining credit; no sandboxes allocated');
    const key = await fetch('https://openrouter.ai/api/v1/key', { headers, signal: AbortSignal.timeout(25_000) });
    if (!key.ok) throw new DemoError('Could not verify the OpenRouter key limit');
    const remaining = (await key.json()).data.limit_remaining;
    if (remaining !== null && remaining !== undefined && remaining <= 0) throw new DemoError('OpenRouter key spending limit exhausted');
    const response = await fetch('https://openrouter.ai/api/v1/models/' + this.state.model + '/endpoints', { signal: AbortSignal.timeout(25_000) });
    if (!response.ok) throw new DemoError('Could not inspect model endpoints');
    const endpoints = (await response.json()).data?.endpoints ?? [];
    if (!endpoints.some((row: { supported_parameters?: string[] }) => ['max_tokens', 'response_format', 'reasoning'].every(p => row.supported_parameters?.includes(p)))) throw new DemoError('No model endpoint supports the requested settings');
    this.state.model_preflight = 'passed'; this.save();
  }
  async model(messages: Message[]): Promise<{ message: Message; meta: Call }> {
    // Only public synthetic examples and official retrieved docs leave the host for this model.
    const started = performance.now();
    this.state.model_requests = (this.state.model_requests ?? 0) + 1; this.save();
    const response = await fetch('https://openrouter.ai/api/v1/chat/completions', { method: 'POST',
      headers: { Authorization: 'Bearer ' + process.env.OPENROUTER_API_KEY, 'Content-Type': 'application/json', 'X-OpenRouter-Title': 'Exa + Render repair comparison' },
      body: JSON.stringify({ model: this.state.model, messages, reasoning: { enabled: false }, max_tokens: contract.max_tokens,
        response_format: { type: 'json_object' }, provider: { require_parameters: true } }), signal: AbortSignal.timeout(90_000) });
    if (!response.ok) throw new DemoError('Model provider returned HTTP ' + response.status);
    const body = await response.json() as { error?: unknown; id?: string; model?: string; usage?: Call['usage']; choices?: { message: Message; finish_reason: string }[] };
    if (body.error || !body.choices?.length) throw new DemoError('Model provider did not return a completion');
    const choice = body.choices[0]!;
    return { message: choice.message, meta: { id: body.id, model: body.model, usage: body.usage,
      seconds: (performance.now() - started) / 1000, finish_reason: choice.finish_reason } };
  }
  async trial(snapshot: string, mode: string, repetition: number) {
    const trial: Trial = { mode, repetition, attempts: [], passed: false }; this.state.trials.push(trial); this.save();
    const sid = await this.create(snapshot); trial.repair_sandbox = sid;
    if (!this.state.fixture_reference) await this.validateFixture(snapshot, sid);
    // Exclude setup and calibration from both modes before measuring repair and verification.
    const started = performance.now();
    let source = shared('starter.py');
    await this.rpc(sid, { op: 'write', source });
    trial.initial = await this.checks(sid, cases.public);
    if (trial.initial.some(row => row.passed)) throw new DemoError('Fixture no longer reproduces all three intended failures');
    trial.search = mode === 'exa' ? await this.search() : null;
    const messages = makeMessages(source, trial.initial, trial.search?.results ?? null);
    for (let n = 0; n < contract.max_attempts; n++) {
      const { message, meta } = await this.model(messages);
      const item: Attempt = { call: meta }; trial.attempts.push(item); this.save();
      if (meta.finish_reason !== 'stop') { item.error = 'Model response was incomplete'; break; }
      let candidate: { source: string; explanation: string };
      try { candidate = parseCandidate(message.content); }
      catch { item.error = 'Invalid candidate JSON or source size'; messages.push(message, { role: 'user', content: item.error }); continue; }
      source = candidate.source; Object.assign(item, candidate, { source_sha256: digest(source) });
      await this.rpc(sid, { op: 'write', source });
      item.public_checks = await this.checks(sid, cases.public); this.save();
      if (item.public_checks.every(row => row.passed)) break;
      messages.push(message, { role: 'user', content: JSON.stringify({ test_feedback: item.public_checks }) });
    }
    // Lock the last submitted bytes before revealing any held-out result, then discard the repair VM.
    const filename = `${mode}-${repetition}-solution.py`; writeFileSync(join(this.output, filename), source);
    trial.candidate_file = filename; trial.source_sha256 = digest(source); await this.terminate(sid);
    const verifier = await this.create(snapshot); trial.verification_sandbox = verifier;
    await this.rpc(verifier, { op: 'write', source });
    trial.verification = await this.checks(verifier, [...cases.public, ...cases.held_out]);
    trial.passed = trial.verification.every(row => row.passed); await this.terminate(verifier);
    trial.seconds = (performance.now() - started) / 1000;
    trial.model_cost_usd = trial.attempts.reduce((sum, attempt) => sum + (attempt.call.usage?.cost ?? 0), 0);
    trial.model_cost_complete = trial.attempts.every(attempt => typeof attempt.call.usage?.cost === 'number');
    this.save(); console.log(`${mode} repetition ${repetition}: ${trial.verification.filter(row => row.passed).length}/15 checks, ${trial.seconds.toFixed(1)}s`);
  }
  async validateFixture(snapshot: string, existingSid?: string) {
    const sid = existingSid ?? await this.create(snapshot);
    this.state.environment = await this.rpc(sid, { op: 'environment' });
    if (this.state.environment.polars !== '2.0.0' || !this.state.environment.credentials_absent) throw new DemoError('Unexpected sandbox environment');
    // Fixed probes check the real environment before any generated code enters it.
    const control = await fetch('https://pypi.org/simple/polars/', { signal: AbortSignal.timeout(10_000) });
    if (!control.ok) throw new DemoError('Network host control failed');
    this.state.network_host_control = control.status;
    const timeout = await this.rpc(sid, { op: 'check', case: {}, driver: 'import time; time.sleep(30)', seconds: 0.3 });
    const output = await this.rpc(sid, { op: 'check', case: {}, driver: "print('x' * 20000)" });
    const network = await this.rpc(sid, { op: 'check', case: {}, driver: "import json, urllib.request\ntry:\n urllib.request.urlopen('https://pypi.org/simple/polars/',timeout=2); print(json.dumps({'blocked':False}))\nexcept Exception:\n print(json.dumps({'blocked':True}))" });
    this.state.network_observation = network;
    this.state.boundary_checks = { timeout: timeout.limit === 'timeout', output_limit: output.limit === 'output_limit',
      network: network.limit === 'timeout' || (network.exit_code === 0 && JSON.parse(network.stdout ?? '{}').blocked === true), credentials_absent: this.state.environment.credentials_absent };
    if (!Object.values(this.state.boundary_checks).every(Boolean)) throw new DemoError('A live sandbox boundary check failed');
    await this.rpc(sid, { op: 'write', source: shared('starter.py') });
    this.state.fixture_initial = await this.checks(sid, cases.public);
    if (this.state.fixture_initial.some(row => row.passed)) throw new DemoError('Fixture no longer reproduces its intended failures');
    await this.rpc(sid, { op: 'write', source: shared('reference.py') });
    this.state.fixture_reference = await this.checks(sid, [...cases.public, ...cases.held_out]); this.save();
    if (!this.state.fixture_reference.every(row => row.passed)) throw new DemoError('Maintainer fixture does not pass its expectations');
    if (!existingSid) await this.terminate(sid);
  }
  async cleanup() {
    const errors: string[] = [];
    for (const record of this.state.sandboxes) {
      try { await this.terminate(record.id); } catch { errors.push(record.id + ': termination unconfirmed'); }
    }
    for (const record of this.state.snapshots) {
      if (record.deleted) continue;
      try {
        try { await this.api.snapshots.delete({ sandboxGroupId: record.group, snapshotId: record.id }); }
        catch { /* An already-deleted snapshot is resolved by the independent list below. */ }
        let cursor: string | undefined; let absent = true; let finished = false;
        for (let n = 0; n < 100; n++) {
          const rows = await this.api.snapshots.list({ sandboxGroupId: record.group, limit: 100, ...(cursor ? { cursor } : {}) });
          absent = absent && !rows.some(row => row.snapshot.id === record.id);
          const next = rows.at(-1)?.cursor;
          if (!rows.length || !next) { finished = true; break; }
          if (cursor === next) throw new DemoError('Snapshot pagination did not advance');
          cursor = next;
        }
        if (!finished || !absent) throw new DemoError('Snapshot deletion unconfirmed');
        record.deleted = true;
      } catch { errors.push(record.id + ': deletion unconfirmed'); }
    }
    if (this.state.pending_create || this.state.pending_snapshot) errors.push('Unknown creation outcome requires provider reconciliation');
    this.state.cleanup_errors = errors; this.state.cleanup_verified = errors.length === 0; this.save();
    if (errors.length) throw new DemoError('Cleanup needs attention; inspect run.json');
  }
}

export function connect(overall: AbortSignal, cleaning: () => boolean) {
  // The SDK captures fetch at construction. Add deadlines before creating it, and always
  // restore the original fetch afterward. Cleanup ignores the cancelled workload signal.
  const original = globalThis.fetch;
  globalThis.fetch = (input, init) => original(input, { ...init, signal: AbortSignal.any([
    AbortSignal.timeout(150_000), ...(init?.signal ? [init.signal] : []), ...(!cleaning() ? [overall] : []),
  ]) });
  try { return { api: new Render().experimental.sandboxes, restore: () => { globalThis.fetch = original; } }; }
  catch (error) { globalThis.fetch = original; throw error; }
}

async function main() {
  // Node's standard argument parser rejects misspelled flags and keeps values out of shell code.
  const { values, positionals } = parseArgs({ allowPositionals: true, options: { 'run-dir': { type: 'string' }, repetitions: { type: 'string', default: '1' }, help: { type: 'boolean' } } });
  if (values.help) { console.log('main.ts compare|smoke|integration|fail-after-create|cleanup [--run-dir PATH] [--repetitions 1..3]'); return; }
  const mode = positionals[0]; const repetitions = Number(values.repetitions);
  if (!['compare', 'smoke', 'integration', 'fail-after-create', 'cleanup'].includes(mode ?? '') || positionals.length !== 1 || ![1, 2, 3].includes(repetitions)) throw new DemoError('Choose a mode and 1..3 repetitions');
  for (const key of ['RENDER_API_KEY', 'RENDER_WORKSPACE_ID', ...(mode === 'compare' ? ['EXA_API_KEY', 'OPENROUTER_API_KEY'] : mode === 'integration' ? ['EXA_API_KEY'] : [])]) if (!process.env[key]) throw new DemoError('Missing ' + key);
  if (process.env.RENDER_USE_LOCAL_DEV || process.env.RENDER_LOCAL_DEV_URL) throw new DemoError('Unset Render local development overrides');
  mkdirSync(join(ROOT, '.runs'), { recursive: true });
  const output = resolve(values['run-dir'] ?? join(ROOT, '.runs', 'typescript-' + randomUUID().slice(0, 10)));
  let cleaning = mode === 'cleanup';
  const controller = new AbortController(); const onSignal = () => controller.abort();
  process.on('SIGINT', onSignal); process.on('SIGTERM', onSignal);
  const connection = connect(AbortSignal.any([controller.signal, AbortSignal.timeout(1200000)]), () => cleaning);
  try {
    let run: Run;
    if (mode === 'cleanup') {
      if (!values['run-dir']) throw new DemoError('cleanup requires --run-dir');
      run = Object.create(Run.prototype) as Run; run.api = connection.api; run.output = output;
      run.state = JSON.parse(readFileSync(join(output, 'run.json'), 'utf8'));
      if (run.state.workspace !== process.env.RENDER_WORKSPACE_ID) throw new DemoError('Cleanup workspace does not match the run');
      await run.cleanup(); return;
    }
    run = new Run(connection.api, output, process.env.OPENROUTER_MODEL ?? contract.model);
    console.log('Run journal: ' + join(output, 'run.json'));
    try {
      if (mode === 'fail-after-create') { await run.create(); throw new DemoError('Intentional failure after allocation'); }
      if (mode === 'compare') await run.preflightModel();
      if (mode === 'integration') { run.state.integration_search = await run.search(); run.save(); }
      const snapshot = await run.prepare();
      if (mode !== 'compare') await run.validateFixture(snapshot);
      if (mode === 'compare') for (let n = 1; n <= repetitions; n++) for (const arm of n % 2 ? ['baseline', 'exa'] : ['exa', 'baseline']) await run.trial(snapshot, arm, n);
      run.state.complete = true;
    } catch (error) {
      run.state.failure = error instanceof DemoError ? error.message : (error as Error).name; throw error;
    } finally {
      cleaning = true; await run.cleanup(); console.log('Cleanup verified: ' + run.state.cleanup_verified);
    }
  } finally {
    connection.restore(); process.off('SIGINT', onSignal); process.off('SIGTERM', onSignal);
  }
}

// Importing this file for tests does not start cloud resources or paid API calls.
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch(error => { console.error(error instanceof DemoError ? error.message : error.name); process.exitCode = 1; });
}

// These local tests use fake cloud responses. Importing the client starts no paid work.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Run, parseCandidate, judge, makeMessages } from '../typescript/main.js';

// Build a runner without its constructor, so there are no files, API calls, or credentials.
function fakeRun() {
  const run = Object.create(Run.prototype) as Run;
  run.state = { sandboxes: [], snapshots: [] } as unknown as Run['state'];
  run.save = () => {};
  return run;
}

test('candidate requires exact fields, strings and bounded bytes', () => {
  const valid = { source: '# Example source\n', explanation: 'Example' };
  assert.deepEqual(parseCandidate(JSON.stringify(valid)), valid);
  for (const value of [null, [], { ...valid, passed: true }, { ...valid, source: ' ' },
    { ...valid, source: 'x'.repeat(24577) }, { ...valid, explanation: false }]) {
    assert.throws(() => parseCandidate(JSON.stringify(value)));
  }
});

test('host judge rejects false claims, wrong order, nonzero exits and limits', () => {
  const row = { name: 'number', input: {}, expected: { result: [1, 2] } };
  const good = { stdout: '{"result":[1,2]}', exit_code: 0 };
  assert.equal(judge(row, good).passed, true);
  for (const changed of [{ stdout: '{"passed":true}' }, { stdout: '{"result":[2,1]}' },
    { stdout: 'not json' }, { stdout: '{"result":[true,2]}' }, { exit_code: 1 }, { limit: 'timeout' }]) {
    assert.equal(judge(row, { ...good, ...changed }).passed, false);
  }
});

test('invalid-date case accepts only the expected error object', () => {
  const row = { name: 'invalid date', input: {}, expected_error: true };
  for (const stdout of ['null', '[]', 'true', '1', '{"error":"ValueError"}']) {
    assert.equal(judge(row, { stdout, exit_code: 0 }).passed, false);
  }
  assert.equal(judge(row, { stdout: '{"error":"InvalidOperationError"}', exit_code: 0 }).passed, true);
});

test('prompts differ only in retrieved documents and exclude hidden tests', () => {
  const a = makeMessages('source', [], null);
  const b = makeMessages('source', [], [{ url: 'https://pola.rs/', title: 'docs', text: 'docs' }]);
  const body = JSON.parse(b[1]!.content); delete body.retrieved_documentation;
  assert.deepEqual(body, JSON.parse(a[1]!.content)); assert.deepEqual(a[0], b[0]);
  assert.equal(a[1]!.content.includes('century boundary'), false);
});

test('lost delete reply resolves through independently confirmed absence', async () => {
  const run = fakeRun();
  run.state.snapshots = [{ id: 'owned', group: 'group', deleted: false }];
  run.api = { snapshots: { delete: async () => { throw new Error('already deleted'); }, list: async () => [] } } as unknown as Run['api'];
  await run.cleanup(); assert.equal(run.state.cleanup_verified, true);
  assert.equal(run.state.snapshots[0]!.deleted, true);
});

test('snapshot found on a later page prevents false cleanup success', async () => {
  const run = fakeRun(); run.state.snapshots = [{ id: 'owned', group: 'group', deleted: false }];
  const pages = [[{ snapshot: { id: 'other' }, cursor: 'next' }], [{ snapshot: { id: 'owned' } }]];
  run.api = { snapshots: { delete: async () => {}, list: async () => pages.shift() } } as unknown as Run['api'];
  await assert.rejects(run.cleanup()); assert.equal(run.state.cleanup_verified, false);
});

test('unknown creation remains unresolved in the journal', async () => {
  const run = fakeRun(); run.state.pending_create = { time: 'example' };
  await assert.rejects(run.cleanup()); assert.equal(run.state.cleanup_verified, false);
});

test('command stream requires an exit event and bounds output', async () => {
  // Simulate streaming API events without running any shell command.
  for (const events of [[{ type: 'output', data: 'partial' }], [{ type: 'output', data: 'x'.repeat(131073) }]]) {
    const run = fakeRun();
    run.api = { exec: async function* () { yield* events; } } as unknown as Run['api'];
    await assert.rejects(run.command('owned', 'trusted command'));
  }
  const run = fakeRun();
  run.api = { exec: async function* () { yield { type: 'output', data: 'ok' }; yield { type: 'exit', exit_code: 0 }; } } as unknown as Run['api'];
  assert.deepEqual(await run.command('owned', 'trusted command'), { exit_code: 0, output: 'ok' });
});

// Restore the network function after this test so it cannot affect another caller.
test('credit preflight stops before any cloud allocation', async () => {
  const run = fakeRun(); run.state.model = 'anthropic/claude-haiku-5.5';
  const original = globalThis.fetch; let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response(JSON.stringify({ data: { total_credits: 1, total_usage: 2 } }), { status: 200 }); };
  try { await assert.rejects(run.preflightModel(), /no remaining credit/); assert.equal(calls, 1); assert.deepEqual(run.state.sandboxes, []); }
  finally { globalThis.fetch = original; }
});

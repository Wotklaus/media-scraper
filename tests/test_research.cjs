const {test} = require('node:test');
const assert = require('node:assert/strict');
const {ResearchWorkspace} = require('../frontend/research.js');

function setup(api) {
    const view = {current: null, rows: [], messageText: '', study(value) { this.current = value; },
        list() {}, capabilities() {}, busy() {}, records(data) { this.rows = data.records; },
        message(text) { this.messageText = text; }, clear() { this.current = null; this.rows = []; }};
    const scheduled = [];
    const workspace = new ResearchWorkspace(api, view, callback => { scheduled.push(callback); return scheduled.length; }, () => {});
    return {workspace, view, scheduled};
}
function deferred() { let resolve; const promise = new Promise(yes => { resolve = yes; }); return {promise, resolve}; }

test('opening reads sources/list only; it never starts a job', async () => {
    const calls = [];
    const {workspace} = setup(async (path, options) => {
        calls.push([path, options]);
        return path.endsWith('sources') ? {synthetic: true} : {studies: [], total: 0, offset: 0, limit: 20};
    });
    await workspace.open();
    assert.equal(calls.length, 2); assert.ok(calls.every(([, options]) => !options));
});
test('stale progress and records cannot replace a different selected study', async () => {
    const old = deferred();
    const {workspace, view} = setup(async path => {
        if (path.includes('/old/progress')) return old.promise;
        return path.includes('/records') ? {records: [{text: 'new'}]} : {study_id: 'new', status: 'draft'};
    });
    const first = workspace.select('old');
    await workspace.select('new');
    old.resolve({study_id: 'old', status: 'acquiring'}); await first;
    assert.equal(view.current.study_id, 'new'); assert.equal(view.rows[0].text, 'new');
});
test('polling only schedules for active studies, close invalidates it', async () => {
    const {workspace, scheduled, view} = setup(async path => path.includes('/records') ? {records: []} : {study_id: 'a', status: 'acquiring'});
    workspace.visible = true; await workspace.select('a'); assert.equal(scheduled.length, 1);
    workspace.close(); await scheduled[0]();
    assert.equal(scheduled.length, 1); assert.equal(view.current.study_id, 'a');
});
test('duplicate command clicks send one POST and errors remain visible', async () => {
    const pending = deferred(), calls = [];
    const {workspace, view} = setup(path => { calls.push(path); return pending.promise; });
    workspace.selected = 'a'; const first = workspace.action('start'); await workspace.action('start');
    assert.equal(calls.length, 1); pending.resolve({study_id: 'different'}); await first;
    workspace.api = async () => { throw new Error('Error seguro de almacenamiento'); };
    await workspace.action('pause'); assert.match(view.messageText, /Error seguro/); assert.equal(workspace.busy, false);
});

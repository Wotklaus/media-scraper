const {test} = require('node:test');
const assert = require('node:assert/strict');
const {BenfordWorkspace} = require('../frontend/benford.js');

function view() {
    return {message: '', data: null, loading: false, rows: [],
        clear(message) { this.message = message; this.data = null; },
        profiles(rows) { this.rows = rows; }, busy(value) { this.loading = value; },
        render(data) { this.data = data; }};
}
function result(username = 'example', metric = 'views', dataset = 'latest') { return {username, metric, dataset}; }
function deferred() { let resolve; const promise = new Promise(yes => { resolve = yes; }); return {promise, resolve}; }

test('opening only reads profiles and empty/error states are explicit', async () => {
    const calls = [], v = view();
    const workspace = new BenfordWorkspace(async path => { calls.push(path); return {profiles: []}; }, v);
    await workspace.open();
    assert.deepEqual(calls, ['/api/stored-profiles']);
    assert.match(v.message, /No hay perfiles/);
    workspace.api = async () => { throw new Error('MongoDB no disponible'); };
    await workspace.open(); assert.equal(v.message, 'MongoDB no disponible');
});
test('analysis runs explicitly with independent metric and dataset, suppressing duplicate clicks', async () => {
    const pending = deferred(), calls = [], v = view();
    const workspace = new BenfordWorkspace(path => { calls.push(path); return pending.promise; }, v);
    const work = workspace.analyze('example', 'comments_count', 'history');
    await workspace.analyze('example', 'comments_count', 'history');
    assert.equal(calls.length, 1); assert.equal(v.loading, true);
    assert.equal(calls[0], '/api/benford/example?metric=comments_count&dataset=history');
    pending.resolve(result('example', 'comments_count', 'history')); await work;
    assert.equal(v.data.metric, 'comments_count'); assert.equal(v.loading, false);
});
test('selection changes invalidate late responses and old errors', async () => {
    const pending = deferred(), v = view();
    const workspace = new BenfordWorkspace(() => pending.promise, v);
    const work = workspace.analyze('example', 'views', 'latest');
    workspace.invalidate();
    workspace.api = async () => result('other', 'likes', 'history');
    await workspace.analyze('other', 'likes', 'history');
    pending.resolve(result()); await work;
    assert.equal(v.data.username, 'other');
});
test('mismatched identity, metric and errors clear results', async () => {
    const v = view(), workspace = new BenfordWorkspace(async () => result('other'), v);
    await workspace.analyze('example', 'views', 'latest');
    assert.match(v.message, /no corresponde/); assert.equal(v.data, null);
    workspace.api = async () => { throw new Error('Servicio no disponible'); };
    await workspace.analyze('example', 'views', 'latest');
    assert.equal(v.message, 'Servicio no disponible'); assert.equal(v.loading, false);
});

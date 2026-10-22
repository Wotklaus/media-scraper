const {test} = require('node:test');
const assert = require('node:assert/strict');
const {BigFiveWorkspace} = require('../frontend/big-five.js');

function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return {promise, resolve, reject};
}
function data(username, ids = [username + '-post']) {
    return {username, profile_id: username.toLowerCase(),
        summary: {generation_pending: 1}, publications: ids.map(publication_id => ({publication_id})),
        related: []};
}
function fixture(api) {
    const view = {
        current: null, message: '', result: '', options: [], disabled: false,
        reset(message) { this.current = null; this.message = message; this.result = ''; this.disabled = true; },
        render(data, busy) { this.current = data; this.disabled = busy; },
        profiles(profiles, selected) { this.options = profiles; this.selected = selected; },
        busy(value) { this.disabled = value; },
        generation(message) { this.result = message; },
    };
    return {view, workspace: new BigFiveWorkspace(api, view)};
}

test('construction does not request data or generate embeddings', () => {
    let calls = 0;
    fixture(() => { calls++; });
    assert.equal(calls, 0);
});

test('entering from General selects the matching stored profile with nickname', async () => {
    const calls = [];
    const profiles = [{username: 'Alpha', nickname: 'Nombre A'}, {username: 'Beta', nickname: 'Nombre B'}];
    const {workspace, view} = fixture(async (path, options) => {
        calls.push([path, options]);
        return path === '/api/stored-profiles' ? {profiles} : data('Beta');
    });
    await workspace.open('BETA');
    assert.equal(view.selected, 'Beta');
    assert.equal(view.options[1].nickname, 'Nombre B');
    assert.equal(view.current.profile_id, 'beta');
    assert.deepEqual(calls.map(call => call[0]), ['/api/stored-profiles', '/api/stored-profiles/Beta/publications']);
    assert.ok(calls.every(call => !call[1]));
});

test('absent General profile does not silently select another profile', async () => {
    const {workspace, view} = fixture(async () => ({profiles: [{username: 'Other'}]}));
    await workspace.open('Missing');
    assert.equal(view.current, null);
    assert.equal(workspace.username, '');
    assert.match(view.message, /no está almacenado/);
});

test('empty profile list has an explicit empty state', async () => {
    const {workspace, view} = fixture(async () => ({profiles: []}));
    await workspace.open();
    assert.equal(view.current, null);
    assert.match(view.message, /no hay perfiles/);
});

test('profile change clears earlier publications, results and indicators immediately', async () => {
    const pending = deferred();
    const {workspace, view} = fixture(path => path.includes('Alpha') ? Promise.resolve(data('Alpha')) : pending.promise);
    await workspace.select('Alpha');
    view.result = 'Alpha generation';
    const loading = workspace.select('Beta');
    assert.equal(view.current, null);
    assert.equal(view.result, '');
    assert.equal(workspace.data, null);
    assert.equal(view.disabled, true);
    pending.resolve(data('Beta'));
    await loading;
    assert.deepEqual(view.current.publications, [{publication_id: 'Beta-post'}]);
});

test('late responses cannot mix A → B → A selections', async () => {
    const requests = [deferred(), deferred(), deferred()];
    let index = 0;
    const {workspace, view} = fixture(() => requests[index++].promise);
    const first = workspace.select('Alpha');
    const second = workspace.select('Beta');
    const third = workspace.select('Alpha');
    requests[2].resolve(data('Alpha', ['new-A']));
    await third;
    requests[1].resolve(data('Beta'));
    requests[0].resolve(data('Alpha', ['old-A']));
    await Promise.all([first, second]);
    assert.deepEqual(view.current.publications, [{publication_id: 'new-A'}]);
});

test('errors from an old selection do not replace the current profile', async () => {
    const pending = deferred();
    const {workspace, view} = fixture(path => path.includes('Alpha') ? pending.promise : Promise.resolve(data('Beta')));
    const first = workspace.select('Alpha');
    await workspace.select('Beta');
    pending.reject(new Error('old-error'));
    await first;
    assert.equal(view.current.username, 'Beta');
    assert.notEqual(view.message, 'old-error');
});

test('generation requires explicit action and duplicate clicks issue one POST', async () => {
    const pending = deferred();
    const calls = [];
    const {workspace, view} = fixture((path, options) => {
        calls.push([path, options]);
        return options?.method === 'POST' ? pending.promise : Promise.resolve(data('Alpha'));
    });
    await workspace.select('Alpha');
    assert.equal(calls.length, 1);
    const generating = workspace.generate();
    await workspace.generate();
    assert.equal(calls.length, 2);
    assert.deepEqual(calls[1], ['/api/embeddings/Alpha?limit=10', {method: 'POST'}]);
    pending.resolve({generated: 1, reused: 0, failed: 0, skipped: 0});
    await generating;
    assert.match(view.result, /Nuevos: 1/);
    assert.equal(calls.length, 3);
});

test('generation finishing after a profile change never renders old results', async () => {
    const pending = deferred();
    const {workspace, view} = fixture((path, options) => options?.method === 'POST'
        ? pending.promise : Promise.resolve(data(path.includes('Alpha') ? 'Alpha' : 'Beta')));
    await workspace.select('Alpha');
    const generating = workspace.generate();
    await workspace.select('Beta');
    pending.resolve({generated: 10, reused: 0, failed: 0, skipped: 0});
    await generating;
    assert.equal(view.current.username, 'Beta');
    assert.equal(view.result, '');
});

test('pending generation stays disabled when switching back to its profile', async () => {
    const pending = deferred();
    const {workspace, view} = fixture((path, options) => options?.method === 'POST'
        ? pending.promise : Promise.resolve(data(path.includes('Alpha') ? 'Alpha' : 'Beta')));
    await workspace.select('Alpha');
    const generating = workspace.generate();
    await workspace.select('Beta');
    await workspace.select('Alpha');
    assert.equal(view.disabled, true);
    pending.resolve({generated: 1, reused: 0, failed: 0, skipped: 0});
    await generating;
    assert.equal(view.disabled, false);
    assert.equal(view.result, '');
});

test('mismatched profile response is rejected without showing its data', async () => {
    const {workspace, view} = fixture(async () => data('Beta'));
    await workspace.select('Alpha');
    assert.equal(view.current, null);
    assert.match(view.message, /no corresponde/);
});

test('generation with no pending descriptions never sends a POST', async () => {
    let calls = 0;
    const {workspace} = fixture(async () => { calls++; return {...data('Alpha'), summary: {generation_pending: 0}}; });
    await workspace.select('Alpha');
    await workspace.generate();
    assert.equal(calls, 1);
});

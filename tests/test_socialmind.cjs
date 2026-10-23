const {test} = require('node:test');
const assert = require('node:assert/strict');
const {strategicDiagnosis, SocialMindWorkspace} = require('../frontend/socialmind.js');
const data = (username = 'a', count = 0) => ({username, profile_id: username, summary: {available: count, generated: 0, pending: count, empty: 0}, related: []});
const current = interpretation => ({profile_id: 'a', status: 'current', analysis: {interpretation}});
function fixture(api) {
    const view = {value: null, message: '', options: [], reset(message) { this.value = null; this.message = message; }, profiles(options) { this.options = options; }, render(value, profile, diagnosis, errors) { this.value = value; this.diagnosis = diagnosis; this.errors = errors; }};
    return {view, workspace: new SocialMindWorkspace(api, view)};
}
test('zero posts and missing interpretation produce no invented themes', () => {
    const result = strategicDiagnosis(data(), null, null);
    assert.match(result.observations.join(' '), /0 publicaciones/);
    assert.match(result.recommendations[0].text, /información adicional/);
    assert.ok(result.recommendations.every(row => row.basis));
});
test('only current supported themes trigger ideas and repetition rules', () => {
    const interpretation = {partial: true, themes: [{name: 'Cocina', publication_ids: ['1', '2']}]};
    const result = strategicDiagnosis(data('a', 2), current(interpretation), null);
    assert.equal(result.recommendations.filter(row => /Cocina/.test(row.text)).length, 2);
    assert.match(result.observations.join(' '), /parcial/);
    assert.ok(!strategicDiagnosis(data(), {...current(interpretation), status: 'stale'}, null).observations.join(' ').includes('Cocina'));
});
test('cosine threshold, pending embeddings and partial OCEAN keep evidence', () => {
    const source = data('a', 3);
    source.related = [{first_publication_id: '1', second_publication_id: '2', similarity: 0.7}, {first_publication_id: '2', second_publication_id: '3', similarity: 0.49}];
    const result = strategicDiagnosis(source, null, current({partial: true, dimensions: [{dimension: 'openness', support_count: 2, total_count: 3, indicators: [{name: 'Exploración', description: 'Lenguaje', publication_ids: ['1', '2']}]}]}));
    assert.match(result.observations.join(' '), /coseno 0.7000/);
    assert.doesNotMatch(result.observations.join(' '), /0.4900/);
    assert.match(result.observations.join(' '), /no puntuaciones psicométricas/);
    assert.ok(result.recommendations.every(row => row.basis));
});
test('empty list and unavailable MongoDB clear previous results', async () => {
    const {workspace, view} = fixture(async () => ({profiles: []}));
    await workspace.open(); assert.match(view.message, /No hay perfiles/);
    workspace.api = async () => { throw new Error('MongoDB no disponible'); };
    await workspace.open(); assert.equal(view.value, null); assert.match(view.message, /MongoDB/);
});
test('partial resources preserve counts and report errors; requests are read only', async () => {
    const calls = [];
    const {workspace, view} = fixture(async (path, options) => {
        calls.push([path, options]);
        if (path.endsWith('/publications')) return data('a', 2);
        if (path.endsWith('/ocean')) throw new Error('No disponible');
        return current({themes: []});
    });
    await workspace.select('a');
    assert.equal(view.value.summary.available, 2); assert.match(view.errors[0], /OCEAN/);
    assert.equal(calls.length, 3); assert.ok(calls.every(([, options]) => !options));
});
test('late A → B → A responses never replace the latest selection', async () => {
    const pending = [];
    const {workspace, view} = fixture(path => path.endsWith('/publications') ? new Promise(resolve => pending.push(resolve)) : Promise.resolve({profile_id: 'a', status: 'missing'}));
    const first = workspace.select('a'), second = workspace.select('b'), third = workspace.select('a');
    assert.equal(view.value, null);
    pending[2](data('a', 3)); await third;
    pending[1](data('b', 2)); pending[0](data('a', 1)); await Promise.all([first, second]);
    assert.equal(view.value.summary.available, 3);
});
test('late insight responses and refreshes are isolated too', async () => {
    let resolveOcean;
    const {workspace, view} = fixture(async path => {
        if (path === '/api/stored-profiles') return {profiles: []};
        if (path.endsWith('/publications')) return data('a', 1);
        if (path.endsWith('/ocean')) return new Promise(resolve => { resolveOcean = resolve; });
        return {profile_id: 'a', status: 'missing'};
    });
    const loading = workspace.select('a');
    await new Promise(resolve => setImmediate(resolve));
    await workspace.open();
    resolveOcean({profile_id: 'a', status: 'missing'}); await loading;
    assert.equal(view.value, null); assert.match(view.message, /No hay perfiles/);
});

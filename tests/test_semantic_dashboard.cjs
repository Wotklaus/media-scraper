const {test} = require('node:test');
const assert = require('node:assert/strict');
const {BigFiveWorkspace, mountBigFive, abbreviate, safeVideoURL} = require('../frontend/big-five.js');

function deferred() {
    let resolve, reject;
    const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
    return {promise, resolve, reject};
}
function source(username = 'Alpha') {
    return {username, profile_id: username.toLowerCase(), model: 'text-embedding-3-small',
        summary: {available: 2, generated: 2, pending: 0, generation_pending: 0},
        publications: [1, 2].map(index => ({publication_id: username + index,
            description: `Texto ${index} ` + 'real '.repeat(40), url: `https://www.tiktok.com/@${username}/video/${index}`}))};
}
function map(username = 'Alpha') {
    const publications = source(username).publications;
    return {profile_id: username.toLowerCase(), rank: 1, explained_variance_ratio: [1, 0],
        points: publications.map((row, index) => ({...row, x: index ? 1 : -1, y: 0})),
        related: [{first: publications[0], second: publications[1], similarity: .123456}]};
}
function analysis(username = 'Alpha') {
    const finding = {text: 'Resumen breve.', publication_ids: [username + '1'],
        evidence: [{publication_id: username + '1', quote: 'Texto 1'}]};
    return {profile_id: username.toLowerCase(), status: 'current', analysis: {
        model: 'gpt-5.4-mini-2026-03-17', interpretation: {summary: finding,
            themes: [{name: 'Tema respaldado', publication_ids: [username + '1'], evidence: finding.evidence}],
            communication_style: [finding]}}};
}
function ocean(username = 'Alpha') {
    const labels = {openness: 'Apertura', conscientiousness: 'Responsabilidad', extraversion: 'Extraversión',
        agreeableness: 'Amabilidad', neuroticism: 'Neuroticismo'};
    return {profile_id: username.toLowerCase(), status: 'current', analysis: {interpretation: {
        dimensions: Object.entries(labels).map(([dimension, name], index) => ({dimension, name,
            description: index ? 'Evidencia insuficiente' : 'Exploración de ideas expresada en el texto.',
            status: index ? 'insufficient_evidence' : 'signals_present', support_count: index ? 0 : 2,
            total_count: 2, presence_index: index ? null : 100,
            indicators: index ? [] : [{name: 'Exploración', description: 'El texto menciona explorar ideas.',
                publication_ids: [username + '1', username + '2'], evidence: [{quote: 'Texto 1'}]}],
            publication_ids: index ? [] : [username + '1', username + '2']}))}}};
}
function response(path, options) {
    const username = path.includes('Beta') ? 'Beta' : 'Alpha';
    const profile_id = username.toLowerCase();
    if (path.endsWith('/publications')) return source(username);
    if (path.endsWith('/map')) return map(username);
    if (path.endsWith('/big-five')) return {profile_id, status: 'unavailable', evaluation: null};
    if (path.endsWith('/analysis')) return options?.method === 'POST'
        ? analysis(username) : {profile_id, status: 'empty', analysis: null};
    if (path.endsWith('/ocean')) return options?.method === 'POST'
        ? ocean(username) : {profile_id, status: 'empty', analysis: null};
    return {profiles: [{username: 'Alpha', nickname: 'Perfil A'}, {username: 'Beta', nickname: 'Perfil B'}]};
}
function controller(api) {
    const view = {events: [], current: null, reset() { this.events = []; this.current = null; },
        render(data) { this.current = data; }, profiles() {}, busy() {}, generation() {},
        analysisBusy(value) { this.loading = value; },
        oceanBusy(value) { this.oceanLoading = value; },
        insight(kind, data, error) { this.events.push({kind, data, error}); }};
    return {workspace: new BigFiveWorkspace(api, view), view};
}

test('selection reads all insights without POST and clears old resources', async () => {
    const calls = [];
    const {workspace, view} = controller(async (path, options) => { calls.push([path, options]); return response(path, options); });
    await workspace.select('Alpha');
    await workspace.select('Beta');
    assert.equal(view.current.profile_id, 'beta');
    assert.equal(view.events.length, 3);
    assert.ok(view.events.every(event => event.data.profile_id === 'beta'));
    assert.ok(calls.every(call => !call[1]));
});

test('late semantic results from Alpha cannot replace Beta', async () => {
    const old = deferred();
    const {workspace, view} = controller((path, options) => path.includes('Alpha') && path.endsWith('/analysis')
        ? old.promise : Promise.resolve(response(path, options)));
    const first = workspace.select('Alpha');
    await new Promise(resolve => setImmediate(resolve));
    await workspace.select('Beta');
    old.resolve(analysis('Alpha'));
    await first;
    assert.ok(view.events.every(event => event.data?.profile_id === 'beta'));
});

test('analysis runs only on demand and duplicate clicks send one POST', async () => {
    const pending = deferred();
    let posts = 0;
    const {workspace, view} = controller(async (path, options) => {
        if (options?.method === 'POST') { posts++; return pending.promise; }
        return response(path, options);
    });
    await workspace.select('Alpha');
    assert.equal(posts, 0);
    const task = workspace.analyze();
    assert.equal(view.loading, true);
    await workspace.analyze();
    assert.equal(posts, 1);
    pending.resolve(analysis());
    await task;
    await workspace.analyze();
    assert.equal(posts, 1);
    assert.equal(view.loading, false);
});

test('analysis loading for old profile does not leak to the next profile', async () => {
    const pending = deferred();
    const {workspace, view} = controller((path, options) => options?.method === 'POST'
        ? pending.promise : Promise.resolve(response(path, options)));
    await workspace.select('Alpha');
    const task = workspace.analyze();
    await workspace.select('Beta');
    pending.resolve(analysis());
    await task;
    assert.equal(workspace.insights.analysis.profile_id, 'beta');
    assert.ok(view.events.every(event => event.data?.profile_id === 'beta'));
});

test('stored current interpretation disables further analysis requests', async () => {
    let posts = 0;
    const {workspace} = controller(async (path, options) => {
        if (options?.method === 'POST') posts++;
        return path.endsWith('/analysis') ? analysis() : response(path, options);
    });
    await workspace.select('Alpha');
    await workspace.analyze();
    assert.equal(posts, 0);
});

test('individual read failures do not discard other modules', async () => {
    const {workspace, view} = controller(async (path, options) => {
        if (path.endsWith('/map')) throw new Error('Map unavailable');
        return response(path, options);
    });
    await workspace.select('Alpha');
    assert.equal(view.current.username, 'Alpha');
    assert.equal(view.events.find(event => event.kind === 'map').error, 'Map unavailable');
    assert.equal(workspace.insights.ocean.status, 'empty');
});

test('provider failure releases the analysis action and displays a safe error', async () => {
    const {workspace, view} = controller(async (path, options) => {
        if (options?.method === 'POST') throw new Error('No se pudo validar el análisis.');
        return response(path, options);
    });
    await workspace.select('Alpha');
    await workspace.analyze();
    assert.equal(view.loading, false);
    assert.equal(workspace.analyzing.size, 0);
    assert.equal(view.events.at(-1).error, 'No se pudo validar el análisis.');
});

class Node {
    constructor(tag = 'div') {
        this.tagName = tag; this.children = []; this.attributes = {}; this.listeners = {};
        this.hidden = false; this.disabled = false; this._text = ''; this.className = '';
        this.style = {};
        this.classList = {add() {}, remove() {}};
    }
    set textContent(value) { this._text = String(value); this.children = []; }
    get textContent() { return this._text + this.children.map(child => child.textContent).join(' '); }
    append(...children) { this.children.push(...children); }
    replaceChildren(...children) { this._text = ''; this.children = children; }
    setAttribute(key, value) { this.attributes[key] = value; }
    addEventListener(event, callback) { this.listeners[event] = callback; }
    all(tag) { return this.children.flatMap(child => [...(child.tagName === tag ? [child] : []), ...child.all(tag)]); }
}
async function dom(run, api = response) {
    const elements = new Map();
    const previous = {document: global.document, fetch: global.fetch, window: global.window};
    global.document = {
        getElementById(id) { if (!elements.has(id)) elements.set(id, new Node()); return elements.get(id); },
        createElement: tag => new Node(tag), createElementNS: (_, tag) => new Node(tag),
    };
    global.fetch = async (path, options) => ({ok: true, json: async () => api(path, options)});
    global.window = {confirm: () => false};
    try { await run(mountBigFive(), id => global.document.getElementById(id)); }
    finally { global.document = previous.document; global.fetch = previous.fetch; global.window = previous.window; }
}

test('SVG renders exactly two projected points, with keyboard and pointer details', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        const svg = element('semanticMap').all('svg')[0];
        assert.equal(svg.attributes.viewBox, '0 0 640 340');
        const circles = svg.all('circle');
        assert.equal(circles.length, 2);
        assert.equal(circles[0].attributes.cy, circles[1].attributes.cy);
        assert.notEqual(circles[0].attributes.cx, circles[1].attributes.cx);
        assert.equal(circles[0].attributes.tabindex, '0');
        circles[0].listeners.mouseenter();
        assert.equal(element('mapDetail').hidden, false);
        assert.ok(element('mapDetail').all('a')[0].href.includes('/video/1'));
        assert.ok(element('mapDetail').all('p')[0].textContent.length <= 120);
        element('mapPointList').children[1].listeners.click();
        assert.match(element('mapDetail').textContent, /Publicación 2/);
    });
});

test('no embeddings renders an empty map without fabricated points', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        assert.equal(element('semanticMap').all('circle').length, 0);
        assert.match(element('semanticMap').textContent, /No hay embeddings/);
    }, path => path.endsWith('/map') ? {...map(), points: [], related: []} : response(path));
});

test('related pairs show abbreviated texts, safe links and four decimal cosine', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        const pairs = element('relatedPublications');
        assert.equal(pairs.children.length, 1);
        assert.equal(pairs.all('a').length, 2);
        assert.ok(pairs.all('p').every(node => node.textContent.length <= 120));
        assert.equal(pairs.all('strong')[0].textContent, '0.1235');
        assert.doesNotMatch(pairs.textContent, /probabilidad|precisión|%/i);
    });
});

test('interpretation replaces the removed themes panel and shows only its own findings', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        await workspace.analyze();
        assert.match(element('semanticInterpretation').textContent, /Resumen breve/);
        assert.equal(element('semanticInterpretation').all('a').length, 2);
        assert.equal(element('analyzeContent').disabled, true);
        const html = require('node:fs').readFileSync(require('node:path').join(__dirname, '../frontend/index.html'), 'utf8');
        assert.doesNotMatch(html, /Temáticas principales|id="semanticThemes"|id="themesEmpty"/);
    });
});

test('OCEAN is the only five-dimension panel and does not request the removed questionnaire', async () => {
    const calls = [];
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        assert.equal(element('oceanDimensions').children.length, 5);
        assert.equal(element('oceanDimensions').all('meter').length, 0);
        const html = require('node:fs').readFileSync(require('node:path').join(__dirname, '../frontend/index.html'), 'utf8');
        assert.match(html, /Big Five · Indicadores OCEAN/);
        assert.doesNotMatch(html, /Evaluación psicométrica independiente|bigFiveDimensions|bigFiveEvaluation|evaluationState/);
        assert.ok(calls.every(([path, options]) => !path.endsWith('/big-five') && options?.method !== 'POST'));
    }, (path, options) => { calls.push([path, options]); return response(path, options); });
});

test('profile reset immediately removes map points, links and stored OCEAN values', async () => {
    const pending = deferred();
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        await workspace.analyze();
        const selecting = workspace.select('Beta');
        assert.equal(element('semanticMap').all('circle').length, 0);
        assert.equal(element('semanticThemes').children.length, 0);
        assert.equal(element('relatedPublications').children.length, 0);
        assert.equal(element('mapDetail').hidden, true);
        assert.equal(element('analyzeContent').disabled, true);
        assert.equal(element('oceanDimensions').all('meter').length, 0);
        pending.resolve(source('Beta'));
        await selecting;
    }, (path, options) => path.includes('Beta') && path.endsWith('/publications') ? pending.promise : response(path, options));
});

test('abbreviations and original-video links reject unsafe URLs', () => {
    assert.equal(abbreviate('a'.repeat(500)).length, 120);
    assert.equal(safeVideoURL('javascript:alert(1)'), null);
    assert.equal(safeVideoURL('https://attacker.invalid/video/1'), null);
    assert.equal(safeVideoURL('https://user:secret@www.tiktok.com/video/1'), null);
    assert.equal(safeVideoURL('https://www.tiktok.com/@x/video/1?token=secret'), 'https://www.tiktok.com/@x/video/1');
});

test('nine stored embeddings display completion and none of the three actions runs on selection', async () => {
    const posts = [];
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        assert.equal(element('generateEmbeddings').disabled, true);
        assert.equal(element('generateEmbeddings').textContent, 'Todos los embeddings están generados');
        assert.match(element('embeddingResult').textContent, /reutilizan los vectores/);
        await workspace.generate();
        await workspace.select('Beta');
        assert.equal(posts.length, 0);
    }, (path, options) => {
        if (options?.method === 'POST') posts.push(path);
        if (path.endsWith('/publications')) return {...source(path.includes('Beta') ? 'Beta' : 'Alpha'),
            summary: {available: 9, generated: 9, pending: 0, generation_pending: 0}};
        return response(path, options);
    });
});

test('OCEAN is paid only on explicit action and uses its own endpoint', async () => {
    const pending = deferred();
    const calls = [];
    const {workspace, view} = controller((path, options) => {
        calls.push([path, options]);
        return options?.method === 'POST' ? pending.promise : Promise.resolve(response(path, options));
    });
    await workspace.select('Alpha');
    assert.ok(calls.every(call => !call[1]));
    const task = workspace.analyzeOcean();
    assert.equal(view.oceanLoading, true);
    await workspace.analyzeOcean();
    assert.equal(calls.filter(call => call[1]?.method === 'POST').length, 1);
    assert.equal(calls.at(-1)[0], '/api/semantics/Alpha/ocean');
    pending.resolve(ocean());
    await task;
    assert.equal(view.oceanLoading, false);
    await workspace.analyzeOcean();
    assert.equal(calls.filter(call => call[1]?.method === 'POST').length, 1);
});

test('OCEAN results finishing after a profile change never mix dimensions', async () => {
    const pending = deferred();
    const {workspace, view} = controller((path, options) => options?.method === 'POST'
        ? pending.promise : Promise.resolve(response(path, options)));
    await workspace.select('Alpha');
    const task = workspace.analyzeOcean();
    await workspace.select('Beta');
    pending.resolve(ocean());
    await task;
    assert.equal(workspace.insights.ocean.profile_id, 'beta');
    assert.ok(view.events.every(event => event.data?.profile_id === 'beta'));
});

test('stored OCEAN renders five linguistic bars without personality scores', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        const dimensions = element('oceanDimensions');
        assert.equal(dimensions.children.length, 5);
        assert.equal(dimensions.all('meter').length, 0);
        assert.equal(dimensions.all('div').filter(node => node.attributes.role === 'progressbar').length, 5);
        assert.match(dimensions.textContent, /100 %/);
        assert.match(dimensions.textContent, /2 de 2 publicaciones/);
        assert.equal(element('analyzeBigFive').disabled, true);
        assert.equal(element('regenerateBigFive').hidden, false);
        assert.equal(dimensions.all('a').length, 2);
    }, (path, options) => path.endsWith('/ocean') ? ocean() : response(path, options));
});

test('fresh OCEAN empty state has no filled indices', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        assert.equal(element('oceanDimensions').all('div').filter(node => node.attributes.role === 'progressbar').length, 5);
        assert.equal(element('oceanDimensions').children.filter(node => /Sin análisis guardado/.test(node.textContent)).length, 5);
        assert.ok(element('oceanDimensions').all('div').filter(node => node.className === 'signal-fill').every(node => node.style.width === '0%'));
        assert.ok(element('oceanDimensions').all('div').filter(node => node.attributes.role === 'progressbar').every(node => node.attributes['aria-valuenow'] === undefined));
        assert.equal(element('regenerateBigFive').hidden, true);
        assert.equal(element('analyzeBigFive').disabled, false);
    });
});

test('regeneration is canceled without cost confirmation and explicit after acceptance', async () => {
    const posts = [];
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        element('regenerateBigFive').listeners.click();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(posts.length, 0);
        await workspace.analyzeOcean({regenerate: true, confirmCost: false});
        assert.equal(posts.length, 0);
        global.window.confirm = () => true;
        element('regenerateBigFive').listeners.click();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(posts.length, 1);
        assert.deepEqual(JSON.parse(posts[0].body), {regenerate: true, confirm_cost: true});
    }, (path, options) => {
        if (options?.method === 'POST') posts.push(options);
        return path.endsWith('/ocean') ? ocean() : response(path, options);
    });
});

test('detailed server error and diagnostic reference reach the content interface', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        global.fetch = async () => ({ok: false, json: async () => ({detail: {
            code: 'output_truncated', message: 'El JSON quedó incompleto; no se guardó.', reference: 'mock-safe-reference'}})});
        await workspace.analyze();
        assert.match(element('semanticResult').textContent, /JSON quedó incompleto/);
        assert.match(element('semanticResult').textContent, /Referencia: mock-safe-reference/);
        assert.equal(element('analyzeContent').disabled, false);
    });
});

test('failed OCEAN regeneration keeps stored dimensions visible', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        global.fetch = async () => ({ok: false, json: async () => ({detail: {message: 'Cuota agotada.', reference: 'mock-ref'}})});
        await workspace.analyzeOcean({regenerate: true, confirmCost: true});
        assert.match(element('oceanResult').textContent, /Cuota agotada/);
        assert.match(element('oceanDimensions').textContent, /100 %/);
        assert.equal(element('regenerateBigFive').disabled, false);
    }, (path, options) => path.endsWith('/ocean') ? ocean() : response(path, options));
});

test('map draws and highlights only qualifying calculated edges without moving points', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        const svg = element('semanticMap').all('svg')[0];
        const lines = svg.all('line');
        assert.equal(lines.length, 1);
        const circles = svg.all('circle');
        const positions = circles.map(node => [node.attributes.cx, node.attributes.cy]);
        circles[0].listeners.click();
        assert.match(circles[0].attributes.class, /is-selected/);
        assert.match(circles[1].attributes.class, /is-related/);
        assert.match(lines[0].attributes.class, /is-active/);
        assert.match(element('relatedPublications').children[0].attributes.class, /is-related/);
        assert.deepEqual(circles.map(node => [node.attributes.cx, node.attributes.cy]), positions);
    }, path => path.endsWith('/map') ? {...map(), related: [{...map().related[0], similarity: .82}]} : response(path));
});

test('weak similarities produce no network edge', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        assert.equal(element('semanticMap').all('line').length, 0);
    });
});

test('partial interpretation with rejected summary still renders verified findings', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        assert.match(element('semanticInterpretation').textContent, /Resultado parcial/);
        assert.match(element('semanticInterpretation').textContent, /Resumen breve/);
        assert.equal(element('analyzeContent').disabled, true);
    }, (path, options) => path.endsWith('/analysis') ? {...analysis(), analysis: {
        ...analysis().analysis, interpretation: {...analysis().analysis.interpretation, summary: null, partial: true}}} : response(path, options));
});

test('explicit absence of content evidence shows insufficient evidence without fabricated findings', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        assert.match(element('semanticInterpretation').textContent, /Evidencia insuficiente/);
        assert.equal(element('semanticInterpretation').all('a').length, 0);
        assert.equal(element('analyzeContent').disabled, true);
    }, (path, options) => path.endsWith('/analysis') ? {...analysis(), analysis: {
        ...analysis().analysis, interpretation: {summary: null, themes: [], communication_style: [],
            partial: false, evidence_status: 'insufficient_evidence'}}} : response(path, options));
});

function savedOceanCounts(counts = [0, 1, 3, 2, 0], total = 10) {
    const stored = ocean();
    stored.analysis.interpretation.dimensions.forEach((row, i) => {
        row.support_count = counts[i]; row.total_count = total;
        // Exercise already-stored reports, including null indices for isolated evidence.
        row.presence_index = null; row.status = 'insufficient_evidence';
        row.description = 'Descripción almacenada sin nuevas conclusiones.';
        row.indicators = counts[i] ? [{name: 'Indicador guardado', description: 'Lenguaje observado.',
            publication_ids: ['Alpha1'], evidence: [{publication_id: 'Alpha1', quote: 'Texto 1'}]}] : [];
    });
    return stored;
}

test('all five bars use stored counts for zero, one and multiple supported publications', async () => {
    const calls = [];
    const stored = savedOceanCounts();
    const before = JSON.stringify(stored);
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        const cards = element('oceanDimensions').children;
        assert.equal(cards.length, 5);
        [0, 10, 30, 20, 0].forEach((percent, i) => {
            const card = cards[i];
            const bar = card.all('div').find(node => node.attributes.role === 'progressbar');
            assert.equal(bar.attributes['aria-valuenow'], percent);
            assert.equal(card.all('div').find(node => node.className === 'signal-fill').style.width, `${percent}%`);
            assert.equal(card.all('strong')[0].textContent, `${percent} %`);
            assert.match(bar.attributes['aria-label'], /no es puntuación de personalidad/);
            assert.equal(card.all('details').length, 1);
        });
        assert.match(cards[0].textContent, /0 de 10 publicaciones.*Sin señales identificadas/);
        assert.match(cards[1].textContent, /1 de 10 publicaciones.*Señal aislada/);
        assert.match(cards[2].textContent, /3 de 10 publicaciones.*Señales observadas/);
        assert.equal(cards[0].all('a').length, 0);
        assert.match(cards[1].all('details')[0].textContent, /Indicador guardado.*Texto 1/);
        assert.equal(cards[1].all('details')[0].attributes.open, undefined);
        assert.equal(element('analyzeBigFive').disabled, true);
        assert.equal(JSON.stringify(stored), before);
        assert.ok(calls.every(([, options]) => options?.method !== 'POST'));
    }, (path, options) => { calls.push([path, options]); return path.endsWith('/ocean') ? stored : response(path, options); });
});

test('presence uses the total analyzed in the saved result and rounds to one decimal', async () => {
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        const card = element('oceanDimensions').children[1];
        assert.match(card.textContent, /33.3 %.*1 de 3 publicaciones/);
        const bar = card.all('div').find(node => node.attributes.role === 'progressbar');
        assert.equal(bar.attributes['aria-valuenow'], 33.3);
    }, (path, options) => path.endsWith('/ocean') ? savedOceanCounts([0,1,2,3,0],3) : response(path, options));
});

test('missing or inconsistent stored counts do not fabricate zero observations', async () => {
    const stored = savedOceanCounts();
    stored.analysis.interpretation.dimensions[0].support_count = undefined;
    stored.analysis.interpretation.dimensions[1].total_count = 0;
    stored.analysis.interpretation.dimensions[2].support_count = 11;
    stored.analysis.interpretation.dimensions.pop();
    await dom(async (workspace, element) => {
        await workspace.select('Alpha');
        const cards = element('oceanDimensions').children;
        assert.equal(cards.length, 5);
        [0, 1, 2, 4].forEach(i => {
            assert.match(cards[i].textContent, /Datos no disponibles/);
            assert.equal(cards[i].all('strong')[0].textContent, '—');
            assert.doesNotMatch(cards[i].textContent, /Sin señales identificadas|0 %/);
        });
    }, (path, options) => path.endsWith('/ocean') ? stored : response(path, options));
});

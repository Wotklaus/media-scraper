'use strict';

// Each generation invalidates previous requests; selection never starts an analysis.
class BenfordWorkspace {
    constructor(api, view) { this.api = api; this.view = view; this.version = 0; this.running = false; }
    invalidate() {
        ++this.version;
        this.running = false;
        this.view.clear('Selecciona los parámetros y pulsa Analizar distribución.');
        this.view.busy(false);
    }
    async open() {
        this.invalidate();
        const version = this.version;
        this.view.profiles([], true);
        this.view.clear('Consultando perfiles almacenados…');
        try {
            const data = await this.api('/api/stored-profiles');
            if (version !== this.version) return;
            this.view.profiles(data.profiles, false);
            this.view.clear(data.profiles.length ? 'Selecciona un perfil y los parámetros del análisis.' : 'No hay perfiles almacenados en MongoDB.');
        } catch (error) {
            if (version === this.version) { this.view.profiles([], false); this.view.clear(error.message); }
        }
    }
    async analyze(username, metric, dataset) {
        if (!username || this.running) return;
        const version = ++this.version;
        this.running = true;
        this.view.clear('Calculando distribución con datos almacenados…');
        this.view.busy(true);
        try {
            const data = await this.api(`/api/benford/${encodeURIComponent(username)}?metric=${encodeURIComponent(metric)}&dataset=${encodeURIComponent(dataset)}`);
            if (version !== this.version) return;
            if (data.username.toLowerCase() !== username.toLowerCase() || data.metric !== metric || data.dataset !== dataset) {
                throw new Error('La respuesta no corresponde a la selección actual.');
            }
            this.view.render(data);
        } catch (error) {
            if (version === this.version) this.view.clear(error.message);
        } finally {
            if (version === this.version) { this.running = false; this.view.busy(false); }
        }
    }
}

async function benfordRequest(path) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
        const response = await fetch(path, {method: 'GET', signal: controller.signal});
        const data = await response.json();
        if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Los parámetros del análisis no son válidos.');
        return data;
    } catch (error) {
        if (error.name === 'AbortError') throw new Error('La consulta excedió 30 segundos. Puedes reintentar.');
        throw error;
    } finally { clearTimeout(timer); }
}

function mountBenford() {
    const el = id => document.getElementById(id);
    const make = (tag, text = '', className = '') => {
        const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
    };
    const number = (value, digits = 2) => value == null ? '—' : new Intl.NumberFormat('es-EC', {maximumFractionDigits: digits}).format(value);
    const svgNode = (tag, attrs, text) => {
        const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
        Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, value));
        if (text !== undefined) node.textContent = text;
        return node;
    };
    function chart(data) {
        // Adapt plot coordinates as well as its size so mobile labels stay readable.
        const width = Math.min(720, Math.max(280, el('benfordResults').clientWidth - 48));
        const step = (width - 75) / 9;
        const barWidth = Math.min(22, step * 0.34);
        const svg = svgNode('svg', {viewBox: `0 0 ${width} 330`, role: 'img', 'aria-label': 'Comparación porcentual por primer dígito: observado y Benford'});
        svg.append(svgNode('title', {}, 'Frecuencias del primer dígito significativo'),
            svgNode('desc', {}, 'Barras azules: frecuencia observada. Barras turquesas: Benford. Los valores exactos aparecen en la tabla.'));
        const max = Math.max(40, ...data.distribution.map(row => row.observed_percent || 0));
        for (let i = 0; i <= 4; i++) {
            const y = 270 - i * 60;
            svg.append(svgNode('line', {x1: 55, x2: width - 15, y1: y, y2: y, stroke: '#dce4ed'}),
                svgNode('text', {x: 48, y: y + 4, 'text-anchor': 'end', 'font-size': 12}, `${number(max * i / 4)}%`));
        }
        data.distribution.forEach((row, index) => {
            const x = 60 + index * step;
            [[row.observed_percent, '#456a95', 0], [row.theoretical_percent, '#20847f', barWidth + 2]].forEach(([value, fill, offset]) => {
                const height = (value || 0) / max * 240;
                const bar = svgNode('rect', {x: x + offset, y: 270 - height, width: barWidth, height, fill, rx: 2});
                bar.append(svgNode('title', {}, `Dígito ${row.digit}: ${offset ? 'Benford' : 'observado'} ${number(value)}%`));
                svg.append(bar);
            });
            svg.append(svgNode('text', {x: x + barWidth + 1, y: 292, 'text-anchor': 'middle', 'font-size': 14}, row.digit));
        });
        svg.append(svgNode('text', {x: width / 2, y: 320, 'text-anchor': 'middle', 'font-size': 13}, 'Primer dígito significativo'));
        return svg;
    }
    const view = {
        clear(message) {
            el('benfordResults').replaceChildren(); el('benfordResults').hidden = true;
            el('benfordStatus').textContent = message;
        },
        busy(value) { el('benfordAnalyze').disabled = value || !el('benfordProfile').value; },
        profiles(rows, loading) {
            const select = el('benfordProfile'); const placeholder = make('option', loading ? 'Cargando perfiles…' : 'Selecciona un perfil'); placeholder.value = '';
            select.replaceChildren(placeholder);
            rows.forEach(row => { const option = make('option', `@${row.username}${row.nickname ? ` · ${row.nickname}` : ''}`); option.value = row.username; select.append(option); });
            select.disabled = loading || !rows.length;
            el('benfordMetric').disabled = loading;
            el('benfordDataset').disabled = loading;
            this.busy(false);
        },
        render(data) {
            const root = el('benfordResults'); root.replaceChildren(); root.hidden = false;
            el('benfordStatus').textContent = `@${data.username} · ${data.metric_label} · ${data.dataset === 'latest' ? 'Última extracción' : 'Historial deduplicado'} · ${data.status === 'empty' ? 'Sin observaciones válidas' : 'Resultado exploratorio'}`;
            const summary = make('div', '', 'benford-summary');
            [['Registros seleccionados', data.total_records], ['Analizados', data.valid_records], ['Excluidos', data.excluded_records],
                ['MAD · escala 0–1', data.mad == null ? null : number(data.mad, 6)], ['χ² · descriptivo', data.chi_squared == null ? null : number(data.chi_squared, 6)]].forEach(([label, value]) => {
                const card = make('article', '', 'card'); card.append(make('span', label), make('strong', value ?? '—')); summary.append(card);
            });
            root.append(summary);
            const notes = make('article', '', 'card benford-notes');
            notes.append(make('h3', 'Selección y calidad de los datos'), make('p', data.selection_policy));
            if (data.run_id) notes.append(make('p', `Extracción: ${data.run_id} · ${data.extracted_at || 'Fecha no disponible'}`));
            notes.append(make('p', `Exclusiones: nulos o ausentes ${data.exclusions.missing}; ceros ${data.exclusions.zero}; negativos ${data.exclusions.negative}; inválidos ${data.exclusions.invalid}. Duplicados eliminados: ${data.duplicates_removed}. Registros sin ID válido omitidos: ${data.invalid_publication_records}.`));
            data.warnings.forEach(warning => notes.append(make('p', warning, 'benford-warning')));
            notes.append(make('p', `Recuentos esperados ≥ 5 en las nueve categorías: ${data.expected_counts_sufficient ? 'sí; no acredita los demás supuestos' : 'no'}. No se calculan valores p ni se realizan pruebas de significación.`));
            root.append(notes);
            const plot = make('article', '', 'card benford-plot'); plot.append(make('h3', 'Frecuencia observada frente a Benford'));
            const legend = make('p', '■ Observado (azul)   ■ Benford (turquesa)', 'benford-legend'); plot.append(legend);
            if (data.valid_records) plot.append(chart(data));
            else plot.append(make('p', 'Sin observaciones válidas: no se representa una distribución observada ficticia.'));
            root.append(plot);
            const tableCard = make('article', '', 'card benford-table');
            const table = make('table'); table.append(make('caption', 'Distribución por primer dígito · Δ en puntos porcentuales'));
            const head = make('thead'), header = make('tr');
            ['Dígito', 'Observados', 'Esperados', 'Observado %', 'Benford %', 'Δ pp'].forEach(label => { const th = make('th', label); th.scope = 'col'; header.append(th); });
            head.append(header); table.append(head); const body = make('tbody');
            data.distribution.forEach(row => {
                const tr = make('tr');
                [row.digit, row.observed_count, number(row.expected_count), number(row.observed_percent), number(row.theoretical_percent), number(row.difference_percentage_points)].forEach(value => tr.append(make('td', value)));
                body.append(tr);
            });
            table.append(body); tableCard.append(table); root.append(tableCard);
            const interpretation = make('article', '', 'card benford-notes');
            interpretation.append(make('h3', 'Interpretación descriptiva'), make('p', `Distribución: ${data.metric_label} · ${data.dataset === 'latest' ? 'última extracción registrada' : 'historial, última observación por publicación'}. ${data.interpretation}`), make('p', data.disclaimer));
            root.append(interpretation);
        },
    };
    const workspace = new BenfordWorkspace(benfordRequest, view);
    el('benfordForm').addEventListener('submit', event => { event.preventDefault(); workspace.analyze(el('benfordProfile').value, el('benfordMetric').value, el('benfordDataset').value); });
    ['benfordProfile', 'benfordMetric', 'benfordDataset'].forEach(id => el(id).addEventListener('change', () => workspace.invalidate()));
    el('benfordRefresh').addEventListener('click', () => workspace.open());
    return workspace;
}

if (typeof module !== 'undefined') module.exports = {BenfordWorkspace};
if (typeof document !== 'undefined') window.benford = mountBenford();

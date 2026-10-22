'use strict';

// A selection version isolates even A → B → A requests that finish out of order.
class BigFiveWorkspace {
    constructor(api, view) {
        this.api = api;
        this.view = view;
        this.username = '';
        this.data = null;
        this.version = 0;
        this.openVersion = 0;
        this.generating = new Set();
        this.analyzing = new Set();
        this.oceanAnalyzing = new Set();
        this.insights = {};
        this.resourceVersions = {};
    }

    async open(preferredUsername = null) {
        const openVersion = ++this.openVersion;
        const preferred = preferredUsername || this.username;
        this.clear('Consultando perfiles almacenados…');
        this.view.profiles([], '', true);
        try {
            const result = await this.api('/api/stored-profiles');
            if (openVersion !== this.openVersion) return;
            const selected = result.profiles.find(profile =>
                profile.username.toLowerCase() === String(preferred).toLowerCase());
            // If General's profile is absent, do not silently analyze another one.
            const username = selected?.username || '';
            this.view.profiles(result.profiles, username, false);
            if (username) await this.select(username);
            else this.clear(result.profiles.length
                ? (preferredUsername ? 'El perfil de General no está almacenado. Selecciona otro perfil.'
                    : 'Selecciona un perfil almacenado para comenzar.')
                : 'Todavía no hay perfiles almacenados en MongoDB.');
        } catch (error) {
            if (openVersion === this.openVersion) this.clear(error.message);
        }
    }

    clear(message) {
        ++this.version;
        this.username = '';
        this.data = null;
        this.insights = {};
        this.view.reset(message);
    }

    async select(username) {
        this.clear(username ? `Cargando @${username}…` : 'Selecciona un perfil almacenado.');
        if (!username) return;
        this.username = username;
        const version = this.version;
        try {
            const data = await this.api(`/api/stored-profiles/${encodeURIComponent(username)}/publications`);
            if (version !== this.version) return;
            if (data.profile_id !== username.toLowerCase()) throw new Error('La respuesta no corresponde al perfil seleccionado.');
            this.data = data;
            this.view.render(data, this.generating.has(username));
            if (this.view.insight) await this.loadInsights(version);
        } catch (error) {
            if (version === this.version) this.view.reset(error.message);
        }
    }

    async generate() {
        const username = this.username;
        const version = this.version;
        if (!this.data?.summary.generation_pending || this.generating.has(username)) return;
        this.generating.add(username);
        this.view.busy(true);
        this.view.generation('Generando embeddings para este perfil…');
        let result;
        try {
            result = await this.api(`/api/embeddings/${encodeURIComponent(username)}?limit=10`, {method: 'POST'});
        } catch (error) {
            if (version === this.version) this.view.generation(error.message);
        } finally {
            this.generating.delete(username);
            if (this.username === username && this.data) this.view.render(this.data, false);
        }
        if (!result) return;
        if (version !== this.version) {
            // Returning to the generating profile refreshes its counts, without
            // attaching the earlier selection's transient result message.
            if (this.username === username) await this.select(username);
            return;
        }
        const refresh = this.select(username);
        const refreshVersion = this.version;
        await refresh;
        if (this.version === refreshVersion && this.username === username && this.data) {
            this.view.generation(`Nuevos: ${result.generated} · Reutilizados: ${result.reused} · Omitidos: ${result.skipped} · Fallidos: ${result.failed}`);
        }
    }

    async loadInsights(version) {
        const username = this.username;
        await Promise.all(['map', 'analysis', 'ocean'].map(async kind => {
            const resourceVersion = (this.resourceVersions[kind] || 0) + 1;
            this.resourceVersions[kind] = resourceVersion;
            try {
                const result = await this.api(`/api/semantics/${encodeURIComponent(username)}/${kind}`);
                if (version !== this.version || resourceVersion !== this.resourceVersions[kind]) return;
                if (result.profile_id !== username.toLowerCase()) throw new Error('El resultado pertenece a otro perfil.');
                this.insights[kind] = result;
                this.view.insight(kind, result, null, result.processing === true || (kind === 'ocean' ? this.oceanAnalyzing : this.analyzing).has(username));
            } catch (error) {
                if (version === this.version && resourceVersion === this.resourceVersions[kind]) {
                    this.insights[kind] = {status: 'error'};
                    this.view.insight(kind, null, error.message, (kind === 'ocean' ? this.oceanAnalyzing : this.analyzing).has(username));
                }
            }
        }));
    }

    async analyze() {
        const username = this.username;
        const version = this.version;
        if (!this.data || this.analyzing.has(username) || this.insights.analysis?.status === 'current'
            || (this.view.insight && !this.insights.analysis)
            || !this.data.publications.slice(0, 10).some(row => typeof row.description === 'string' && row.description.trim())) return;
        this.analyzing.add(username);
        this.view.analysisBusy(true);
        let result;
        try {
            result = await this.api(`/api/semantics/${encodeURIComponent(username)}/analysis`, {method: 'POST'});
            if (result.profile_id !== username.toLowerCase()) throw new Error('El resultado pertenece a otro perfil.');
            if (version === this.version) {
                this.resourceVersions.analysis = (this.resourceVersions.analysis || 0) + 1;
                this.insights.analysis = result;
                this.view.insight('analysis', result, null, false);
            }
        } catch (error) {
            if (version === this.version) this.view.insight('analysis', null, error.message, false);
        } finally {
            this.analyzing.delete(username);
            if (this.username === username) this.view.analysisBusy(false, this.insights.analysis?.status === 'current');
        }
        if (result && version !== this.version && this.username === username && this.data) {
            await this.loadInsights(this.version);
        }
    }

    async analyzeOcean({regenerate = false, confirmCost = false} = {}) {
        const username = this.username;
        const version = this.version;
        const status = this.insights.ocean?.status;
        if (!this.data || !status || status === 'processing' || this.insights.ocean?.processing || this.oceanAnalyzing.has(username)
            || (status === 'current' && !regenerate) || (regenerate && !confirmCost)
            || !this.data.publications.slice(0, 10).some(row => typeof row.description === 'string' && row.description.trim())) return;
        this.oceanAnalyzing.add(username);
        this.view.oceanBusy(true);
        let result;
        try {
            result = await this.api(`/api/semantics/${encodeURIComponent(username)}/ocean`, {
                method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({regenerate, confirm_cost: confirmCost})});
            if (result.profile_id !== username.toLowerCase()) throw new Error('El resultado pertenece a otro perfil.');
            if (version === this.version) {
                this.resourceVersions.ocean = (this.resourceVersions.ocean || 0) + 1;
                this.insights.ocean = result;
                this.view.insight('ocean', result, null, false);
            }
        } catch (error) {
            if (version === this.version) this.view.insight('ocean', this.insights.ocean, error.message, false);
        } finally {
            this.oceanAnalyzing.delete(username);
            if (this.username === username) this.view.oceanBusy(false, this.insights.ocean?.status === 'current');
        }
        if (result && version !== this.version && this.username === username && this.data) await this.loadInsights(this.version);
    }
}

async function storedRequest(path, options = {}) {
    const response = await fetch(path, options);
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
        const detail = result.detail;
        const message = typeof detail === 'string' ? detail : typeof detail?.message === 'string'
            ? detail.message + (detail.reference ? ` Referencia: ${detail.reference}` : '')
            : 'No se pudieron consultar los datos almacenados.';
        throw new Error(message);
    }
    return result;
}

const abbreviate = (value, length = 120) => {
    const text = String(value || 'Sin descripción').replace(/\s+/g, ' ').trim();
    return text.length > length ? text.slice(0, length - 1) + '…' : text;
};

function safeVideoURL(value) {
    try {
        const url = new URL(value);
        return url.protocol === 'https:' && url.host === 'www.tiktok.com' && !url.username && !url.password
            && url.pathname.includes('/video/') ? url.origin + url.pathname : null;
    } catch { return null; }
}

const TRAIT_LABELS = {openness: 'Apertura', conscientiousness: 'Responsabilidad',
    extraversion: 'Extraversión', agreeableness: 'Amabilidad', neuroticism: 'Neuroticismo'};

function mountBigFive() {
    const element = id => document.getElementById(id);
    const selector = element('storedProfile');
    const generate = element('generateEmbeddings');
    const analyze = element('analyzeContent');
    const oceanButton = element('analyzeBigFive');
    const regenerateOcean = element('regenerateBigFive');
    let currentData = null;
    let analysisCurrent = false;
    let oceanCurrent = false;
    const make = (tag, text, className = '') => {
        const node = document.createElement(tag);
        node.textContent = text;
        node.className = className;
        return node;
    };
    const empty = (id, text) => element(id).replaceChildren(make('p', text, 'empty-message'));
    const videoLink = (row, label = 'Ver publicación ↗') => {
        const url = safeVideoURL(row.url);
        const node = make(url ? 'a' : 'span', url ? label : 'Enlace no disponible', 'bf-video-link');
        if (url) { node.href = url; node.target = '_blank'; node.rel = 'noopener noreferrer'; }
        return node;
    };
    const evidenceLinks = ids => {
        const group = make('div', '', 'evidence-links');
        ids.forEach(id => {
            const row = currentData?.publications.find(row => row.publication_id === id);
            if (row) group.append(videoLink(row, `Publicación ${currentData.publications.indexOf(row) + 1} ↗`));
        });
        return group;
    };
    function oceanDimensions(report = null) {
        const byDimension = new Map((report?.dimensions || []).map(row => [row.dimension, row]));
        element('oceanDimensions').replaceChildren(...Object.entries(TRAIT_LABELS).map(([key, label]) => {
            const dimension = byDimension.get(key);
            const card = make('div', '', 'ocean-dimension');
            card.append(make('h4', label));
            const support = dimension?.support_count;
            const total = dimension?.total_count;
            const validCounts = Number.isInteger(support) && Number.isInteger(total)
                && support >= 0 && total > 0 && support <= total;
            // Saved presence_index may be null for a single supported post. Use saved counts,
            // independent of the backend's former two-publication sufficiency threshold.
            const index = validCounts ? Math.round(support / total * 1000) / 10 : null;
            const state = !validCounts ? (report ? 'Datos no disponibles' : 'Sin análisis guardado')
                : support === 0 ? 'Sin señales identificadas' : support === 1 ? 'Señal aislada' : 'Señales observadas';
            card.append(make('strong', index === null ? '—' : `${index} %`, 'signal-index'));
            const bar = make('div', '', 'signal-track');
            bar.setAttribute('role', 'progressbar');
            bar.setAttribute('aria-label', `Presencia de señales lingüísticas de ${label}; no es puntuación de personalidad`);
            bar.setAttribute('aria-valuemin', '0'); bar.setAttribute('aria-valuemax', '100');
            if (index !== null) bar.setAttribute('aria-valuenow', index);
            bar.setAttribute('aria-valuetext', index === null ? state : `${index} %; ${support} de ${total} publicaciones; ${state}`);
            const fill = make('div', '', 'signal-fill');
            fill.style.width = `${index ?? 0}%`;
            bar.append(fill);
            card.append(bar, make('small', validCounts ? `${support} de ${total} publicaciones con señales` : '— de — publicaciones con señales'),
                make('p', state, 'ocean-description'));
            const details = document.createElement('details');
            details.append(make('summary', 'Indicadores y evidencias'));
            const content = make('div', '', 'ocean-detail-content');
            const indicators = Array.isArray(dimension?.indicators) ? dimension.indicators : [];
            if (validCounts && support > 0 && dimension.description) {
                content.append(make('p', dimension.description));
            }
            indicators.forEach(indicator => {
                const block = make('div', '', 'ocean-evidence');
                block.append(make('strong', indicator.name), make('p', indicator.description),
                    evidenceLinks(indicator.publication_ids));
                indicator.evidence.forEach(item => block.append(make('p', `“${item.quote}”`, 'signal-quote')));
                content.append(block);
            });
            if (!indicators.length) content.append(make('p', 'No hay indicadores ni evidencias disponibles.'));
            details.append(content);
            card.append(details);
            return card;
        }));
    }
    const summary = data => {
        element('embeddingSummary').replaceChildren(...[
            ['Publicaciones disponibles', data?.available ?? '—'],
            ['Embeddings vigentes', data?.generated ?? '—'],
            ['Embeddings pendientes', data?.pending ?? '—'],
        ].map(([label, value]) => {
            const card = make('div', '', 'bf-stat');
            card.append(make('span', label), make('strong', value));
            return card;
        }));
        ['Available', 'Generated', 'Pending'].forEach((key, index) => {
            element('panel' + key).textContent = data?.[['available', 'generated', 'pending'][index]] ?? '—';
        });
    };
    function renderMap(data) {
        const container = element('semanticMap');
        container.replaceChildren();
        element('mapPointList').replaceChildren();
        element('mapDetail').hidden = true;
        element('mapCount').textContent = `${data.points.length} puntos`;
        if (!data.points.length) { empty('semanticMap', 'No hay embeddings vigentes para proyectar.'); return; }
        const ns = 'http://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('viewBox', '0 0 640 340');
        svg.setAttribute('aria-label', 'PCA: cada punto representa una publicación real');
        const svgNode = (tag, attrs) => {
            const node = document.createElementNS(ns, tag);
            Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
            return node;
        };
        // One uniform scale preserves the real centered PCA geometry. No jitter or force layout.
        const scale = Math.max(...data.points.map(point => Math.max(Math.abs(point.x) / 270, Math.abs(point.y) / 135))) || 1;
        const positions = new Map(data.points.map(point => [point.publication_id,
            {x: 320 + point.x / scale, y: 170 - point.y / scale}]));
        const pairs = data.related.filter(pair => Number.isFinite(pair.similarity) && pair.similarity >= 0.5
            && positions.has(pair.first.publication_id) && positions.has(pair.second.publication_id));
        const edges = pairs.map(pair => {
            const a = positions.get(pair.first.publication_id), b = positions.get(pair.second.publication_id);
            const line = svgNode('line', {x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: 'map-edge',
                'stroke-width': 0.8 + pair.similarity});
            const title = svgNode('title', {});
            title.textContent = `Similitud coseno: ${pair.similarity.toFixed(4)}`;
            line.append(title); svg.append(line);
            return {line, pair};
        });
        const circles = [], buttons = [];
        const labels = [];
        const choose = (point, index) => {
            const connected = data.related.filter(pair => pair.first.publication_id === point.publication_id
                || pair.second.publication_id === point.publication_id);
            const neighbors = new Set(connected.flatMap(pair => [pair.first.publication_id, pair.second.publication_id]));
            circles.forEach((circle, i) => {
                const selected = i === index;
                circle.setAttribute('class', `map-dot${selected ? ' is-selected' : neighbors.has(data.points[i].publication_id) ? ' is-related' : ' is-muted'}`);
                circle.setAttribute('aria-pressed', String(selected));
                buttons[i].setAttribute('aria-pressed', String(selected));
            });
            edges.forEach(({line, pair}) => line.setAttribute('class', 'map-edge' + (
                pair.first.publication_id === point.publication_id || pair.second.publication_id === point.publication_id ? ' is-active' : '')));
            element('mapDetail').replaceChildren(make('small', 'PUBLICACIÓN SELECCIONADA'),
                make('strong', `Publicación ${index + 1}`), make('p', abbreviate(point.description)), videoLink(point));
            if (connected.length) {
                element('mapDetail').append(make('small', 'RELACIONES · COSENO'));
                connected.slice(0, 3).forEach(pair => {
                    const other = pair.first.publication_id === point.publication_id ? pair.second : pair.first;
                    const n = data.points.findIndex(row => row.publication_id === other.publication_id);
                    const link = make('button', `Publicación ${n + 1} · ${pair.similarity.toFixed(3)}`, 'map-related-button');
                    link.type = 'button';
                    link.addEventListener('click', () => choose(data.points[n], n));
                    element('mapDetail').append(link);
                });
            }
            element('mapDetail').hidden = false;
            // Highlight the corresponding pairs in the related publications list too.
            Array.from(element('relatedPublications').children).forEach((row, i) => {
                const pair = data.related[i];
                row.setAttribute('class', 'related-pair' + (pair && (pair.first.publication_id === point.publication_id
                    || pair.second.publication_id === point.publication_id) ? ' is-related' : ''));
            });
        };
        data.points.forEach((point, index) => {
            const {x, y} = positions.get(point.publication_id);
            const degree = pairs.filter(pair => pair.first.publication_id === point.publication_id || pair.second.publication_id === point.publication_id).length;
            const radius = 8 + Math.min(degree, 4) * 1.5;
            const circle = svgNode('circle', {cx: x, cy: y, r: radius, tabindex: 0, role: 'button',
                'aria-pressed': 'false', 'aria-label': `Publicación ${index + 1}: ${abbreviate(point.description)}`, class: 'map-dot'});
            const title = svgNode('title', {});
            title.textContent = abbreviate(point.description);
            circle.append(title);
            const select = () => choose(point, index);
            // Hover is transient styling; selection and its detail panel remain stable.
            circle.addEventListener('mouseenter', () => { if (element('mapDetail').hidden) select(); });
            ['focus', 'click'].forEach(event => circle.addEventListener(event, select));
            circle.addEventListener('keydown', event => { if (['Enter', ' '].includes(event.key)) { event.preventDefault(); select(); } });
            svg.append(circle);
            circles.push(circle);
            // Label placement avoids every node and accepted label, hiding if no slot is free.
            const candidates = [[radius + 7, -radius - 2], [radius + 7, radius + 13], [-radius - 25, -radius - 2], [-radius - 25, radius + 13]];
            const slot = candidates.map(([dx, dy]) => ({x: x + dx, y: y + dy})).find(pos =>
                pos.x > 8 && pos.x < 605 && pos.y > 18 && pos.y < 328
                && !labels.some(label => Math.abs(label.x - pos.x) < 30 && Math.abs(label.y - pos.y) < 19)
                && ![...positions.values()].some(node => Math.abs(node.x - (pos.x + 8)) < 25 && Math.abs(node.y - (pos.y - 5)) < 24));
            if (slot) {
                const label = svgNode('text', {x: slot.x, y: slot.y, class: 'map-label', 'aria-hidden': 'true'});
                label.textContent = String(index + 1).padStart(2, '0'); svg.append(label); labels.push(slot);
            }
            const button = make('button', `${index + 1}`, 'map-point-button');
            button.type = 'button';
            button.setAttribute('aria-label', `Seleccionar publicación ${index + 1}`);
            button.addEventListener('click', select);
            buttons.push(button);
            element('mapPointList').append(button);
        });
        container.append(svg);
        const variance = data.explained_variance_ratio.reduce((a, b) => a + b, 0);
        element('mapNote').textContent = `PCA · Varianza conservada: ${(variance * 100).toFixed(1)} %. La distancia visual no equivale al coseno exacto.${data.rank === 0 ? ' Los vectores coinciden; los puntos se superponen.' : ''}`;
    }
    function renderRelated(pairs) {
        element('relatedPublications').replaceChildren(...pairs.map(pair => {
            const item = make('li', '', 'related-pair');
            const texts = make('div', '', 'pair-texts');
            [['A', pair.first], ['B', pair.second]].forEach(([label, row]) => {
                const post = make('div', '', 'pair-post');
                post.append(make('span', label, 'pair-label'), make('p', abbreviate(row.description)), videoLink(row));
                texts.append(post);
            });
            item.append(texts, make('strong', pair.similarity.toFixed(4), 'cosine-value'));
            return item;
        }));
        element('relatedEmpty').hidden = pairs.length > 0;
    }
    const view = {
        profiles(profiles, selected, loading) {
            selector.replaceChildren();
            const placeholder = make('option', loading ? 'Cargando perfiles…' : 'Selecciona un perfil');
            placeholder.value = '';
            selector.append(placeholder);
            profiles.forEach(profile => {
                const option = make('option', `${profile.nickname || profile.username} (@${profile.username})`);
                option.value = profile.username;
                selector.append(option);
            });
            selector.value = selected;
            selector.disabled = loading || !profiles.length;
        },
        reset(message) {
            currentData = null;
            analysisCurrent = false;
            oceanCurrent = false;
            summary(null);
            element('bigFiveStatus').textContent = message;
            element('relatedPublications').replaceChildren();
            element('relatedEmpty').hidden = false;
            element('relatedEmpty').textContent = 'Se necesitan al menos dos embeddings vigentes.';
            element('semanticInterpretation').replaceChildren();
            element('analysisState').textContent = 'Sin análisis';
            element('semanticAnalysisModel').textContent = 'Análisis textual con OpenAI';
            element('semanticResult').textContent = '';
            element('mapPointList').replaceChildren();
            element('mapDetail').replaceChildren();
            element('mapDetail').hidden = true;
            element('mapCount').textContent = '0 puntos';
            element('mapNote').textContent = 'La distancia proyectada no equivale a la similitud coseno exacta.';
            empty('semanticMap', 'Selecciona un perfil con embeddings vigentes.');
            element('semanticMap').setAttribute('aria-busy', 'false');
            element('embeddingResult').textContent = '';
            element('embeddingScope').textContent = 'Bajo demanda · Hasta 10 publicaciones · Tiene costo';
            oceanDimensions();
            element('oceanState').textContent = 'Sin análisis';
            element('oceanResult').textContent = '';
            regenerateOcean.hidden = true;
            this.oceanBusy(false);
            oceanButton.disabled = true;
            this.busy(false);
            this.analysisBusy(false);
            generate.disabled = true;
            analyze.disabled = true;
        },
        busy(value) {
            generate.disabled = value;
            generate.setAttribute('aria-busy', String(value));
            generate.textContent = value ? 'Generando…' : 'Generar embeddings';
        },
        analysisBusy(value, current = analysisCurrent) {
            const validText = currentData?.publications.slice(0, 10).some(row => typeof row.description === 'string' && row.description.trim());
            analyze.disabled = value || current || !validText || workspace.insights.analysis?.status === 'processing';
            analyze.setAttribute('aria-busy', String(value));
            analyze.textContent = value ? 'Analizando…' : 'Analizar contenido con OpenAI';
            if (value) element('semanticResult').textContent = 'Analizando las descripciones…';
        },
        oceanBusy(value, current = oceanCurrent) {
            value = value || workspace.insights.ocean?.processing === true;
            const validText = currentData?.publications.slice(0, 10).some(row => typeof row.description === 'string' && row.description.trim());
            oceanButton.disabled = value || current || !validText || workspace.insights.ocean?.status === 'processing';
            oceanButton.textContent = value ? 'Analizando Big Five…' : 'Analizar Big Five';
            oceanButton.setAttribute('aria-busy', String(value));
            regenerateOcean.disabled = value || !current || !validText;
            if (value) element('oceanResult').textContent = 'Analizando señales lingüísticas…';
        },
        generation(message) { element('embeddingResult').textContent = message; },
        render(data, busy) {
            currentData = data;
            summary(data.summary);
            element('embeddingModel').textContent = data.model;
            element('embeddingScope').textContent = `Primeras 10 publicaciones · ${data.summary.generation_pending} pendientes en este grupo · Tiene costo`;
            element('bigFiveStatus').textContent = `@${data.username} · MongoDB Atlas`;
            this.busy(busy);
            generate.disabled = busy || !data.summary.generation_pending;
            if (!busy && data.summary.pending === 0 && data.summary.generated > 0) {
                generate.textContent = 'Todos los embeddings están generados';
                element('embeddingResult').textContent = 'Se reutilizan los vectores almacenados. No se generarán de nuevo.';
            }
            this.analysisBusy(workspace.analyzing.has(data.username));
            if (!workspace.insights.analysis) analyze.disabled = true;
            this.oceanBusy(workspace.oceanAnalyzing.has(data.username));
            if (!workspace.insights.ocean) oceanButton.disabled = true;
            if (!workspace.insights.map) {
                empty('semanticMap', 'Calculando la proyección de los vectores almacenados…');
                element('semanticMap').setAttribute('aria-busy', 'true');
                element('relatedEmpty').textContent = 'Consultando relaciones…';
            }
            if (!workspace.insights.analysis) {
                element('analysisState').textContent = 'Cargando';
                element('semanticResult').textContent = 'Consultando análisis almacenado…';
            }
        },
        insight(kind, data, error, busy) {
            if (kind === 'map') {
                element('semanticMap').setAttribute('aria-busy', 'false');
                element('relatedEmpty').textContent = 'Se necesitan al menos dos embeddings vigentes.';
                if (error) {
                    empty('semanticMap', error);
                    element('relatedEmpty').textContent = 'No se pudieron calcular las relaciones.';
                } else { renderMap(data); renderRelated(data.related); }
            } else if (kind === 'analysis') {
                analysisCurrent = data?.status === 'current';
                element('semanticInterpretation').replaceChildren();
                const interpretation = analysisCurrent ? data.analysis.interpretation : null;
                element('analysisState').textContent = analysisCurrent ? 'Vigente' : data?.status === 'stale' ? 'Contenido actualizado' : 'Sin análisis';
                element('semanticResult').textContent = error || data?.error?.message || (data?.status === 'processing' ? 'Hay una solicitud en curso; no se iniciará otra automáticamente.' : data?.status === 'stale' ? 'El contenido cambió. Genera un nuevo análisis.' : data?.reused ? 'Análisis almacenado reutilizado.' : analysisCurrent ? 'Análisis guardado.' : 'Todavía no hay un análisis generado.');
                if (interpretation) {
                    element('semanticAnalysisModel').textContent = data.analysis.model;
                    if (interpretation.evidence_status === 'insufficient_evidence') element('semanticInterpretation').append(make('p', 'Evidencia insuficiente para formular hallazgos verificables.', 'bf-caption'));
                    if (interpretation.summary) element('semanticInterpretation').append(make('p', interpretation.summary.text, 'semantic-summary'),
                        evidenceLinks(interpretation.summary.publication_ids));
                    if (interpretation.partial) element('semanticInterpretation').append(make('p', 'Resultado parcial: se muestran solo hallazgos verificados.', 'bf-caption'));
                    interpretation.communication_style.forEach(finding => {
                        const block = make('div', '', 'semantic-finding');
                        block.append(make('p', finding.text), evidenceLinks(finding.publication_ids));
                        element('semanticInterpretation').append(block);
                    });

                }
                this.analysisBusy(busy);
            } else if (kind === 'ocean') {
                oceanCurrent = data?.status === 'current';
                oceanDimensions(oceanCurrent ? data.analysis.interpretation : null);
                regenerateOcean.hidden = !oceanCurrent;
                element('oceanState').textContent = oceanCurrent ? 'Exploratorio · Vigente' : 'Exploratorio';
                element('oceanResult').textContent = error || data?.error?.message || (oceanCurrent
                    ? (data.analysis.interpretation.partial ? 'Resultado parcial: solo indicadores verificados.' : data.reused ? 'Resultado almacenado reutilizado.' : 'Resultado exploratorio guardado.')
                    : data?.status === 'stale' ? 'El contenido cambió. Puedes solicitar un nuevo análisis.'
                    : data?.status === 'processing' ? 'Hay una solicitud en curso; no se iniciará otra automáticamente.'
                    : 'Sin análisis lingüístico generado.');
                this.oceanBusy(busy);
            }
        },
    };
    const workspace = new BigFiveWorkspace(storedRequest, view);
    selector.addEventListener('change', () => workspace.select(selector.value));
    generate.addEventListener('click', () => workspace.generate());
    analyze.addEventListener('click', () => workspace.analyze());
    oceanButton.addEventListener('click', () => workspace.analyzeOcean());
    regenerateOcean.addEventListener('click', () => {
        if (window.confirm('Regenerar Big Five hará una nueva solicitud pagada a OpenAI para este perfil. ¿Confirmas el costo?')) {
            workspace.analyzeOcean({regenerate: true, confirmCost: true});
        }
    });
    element('refreshStoredProfiles').addEventListener('click', () => workspace.open());
    view.reset('Selecciona Big Five para consultar los perfiles de MongoDB.');
    return workspace;
}

if (typeof module !== 'undefined') module.exports = {BigFiveWorkspace, abbreviate, safeVideoURL, mountBigFive};
if (typeof document !== 'undefined') window.bigFive = mountBigFive();

'use strict';

// Recommendations use only current, stored evidence. No generation endpoints are exposed.
function strategicDiagnosis(data, analysis, ocean) {
    const observations = [], recommendations = [];
    const statusLabel = resource => ({missing: 'sin análisis guardado', unavailable: 'no disponible', stale: 'desactualizado', processing: 'en proceso; no se inicia otra solicitud', error: 'error de consulta'}[resource?.status] || 'no disponible');
    const summary = data.summary;
    const add = (text, basis, title, type, ids = []) => recommendations.push({text, basis, title, type, ids});
    observations.push(`${summary.available} publicaciones disponibles; ${summary.generated} embeddings vigentes; ${summary.pending} pendientes; ${summary.empty ?? 'sin dato'} sin texto utilizable.`);
    const interpretation = analysis?.status === 'current' ? analysis.analysis?.interpretation : null;
    const themes = (interpretation?.themes || []).filter(theme => theme.name && theme.publication_ids?.length);
    observations.push(interpretation ? `Interpretación guardada vigente${interpretation.partial ? ' · parcial: solo hallazgos verificados' : ''}.` : `Temáticas no disponibles: interpretación ${statusLabel(analysis)}.`);
    themes.forEach(theme => {
        const basis = `Tema «${theme.name}»; publicaciones: ${theme.publication_ids.join(', ')}.`;
        observations.push(basis);
        add(`Usar «${theme.name}» como punto de partida para proponer ideas de contenido.`, basis, 'Ideas desde tus temas', 'Contenido', theme.publication_ids);
        if (new Set(theme.publication_ids).size >= 2) add(`Explorar contenido complementario a «${theme.name}».`, `Tema repetido en ${new Set(theme.publication_ids).size} publicaciones: ${theme.publication_ids.join(', ')}.`, 'Ampliar el enfoque', 'Contenido', theme.publication_ids);
    });
    if (interpretation && !themes.length) observations.push('La interpretación no contiene temáticas respaldadas.');
    const related = (data.related || []).filter(pair => Number.isFinite(pair.similarity) && pair.similarity >= 0.5);
    related.forEach(pair => observations.push(`Relación entre ${pair.first_publication_id} y ${pair.second_publication_id}: coseno ${pair.similarity.toFixed(4)}.`));
    if (related.length) add('Revisar qué enfoques temáticos comparten las publicaciones relacionadas; la similitud no identifica por sí sola un tema.', `Pares con coseno ≥ 0.50 entre los cinco pares devueltos: ${related.map(pair => `${pair.first_publication_id} / ${pair.second_publication_id} (${pair.similarity.toFixed(4)})`).join('; ')}.`, 'Explorar conexiones', 'Contenido', [...new Set(related.flatMap(pair => [pair.first_publication_id, pair.second_publication_id]))]);
    else observations.push('No hay pares con coseno ≥ 0.50 entre los cinco pares devueltos.');
    const signals = ocean?.status === 'current' ? ocean.analysis?.interpretation : null;
    observations.push(signals ? `OCEAN guardado vigente${signals.partial ? ' · parcial' : ''}. Señales exploratorias, no puntuaciones psicométricas.` : `Señales OCEAN no disponibles: ${statusLabel(ocean)}.`);
    (signals?.dimensions || []).forEach(dimension => {
        observations.push(`${dimension.dimension}: ${dimension.support_count ?? 'sin dato'} publicaciones con señales de ${dimension.total_count ?? 'sin dato'} analizadas.`);
        if (!dimension.indicators?.length) observations.push(`${dimension.dimension}: sin indicadores respaldados disponibles.`);
        (dimension.indicators || []).forEach(indicator => observations.push(`${indicator.name}: ${indicator.description} Respaldo: ${(indicator.publication_ids || []).join(', ')}.`));
    });
    if (summary.available < 2 || (!themes.length && !related.length)) add('Reunir información adicional autorizada antes de formular una estrategia de contenido.', `${summary.available} publicaciones disponibles; ${themes.length} temas vigentes respaldados y ${related.length} pares con coseno ≥ 0.50.`, 'Reforzar la evidencia', 'Datos');
    if (summary.pending > 0) add('Completar la cobertura semántica antes de ampliar conclusiones; esta pestaña no genera embeddings.', `${summary.pending} publicaciones con texto sin embedding vigente.`, 'Completar la cobertura', 'Datos', data.publications?.filter(row => row.embedding_status === 'pending').map(row => row.publication_id));
    return {observations, recommendations, summary, themes, related, interpretation, signals, analysisStatus: statusLabel(analysis), oceanStatus: statusLabel(ocean)};
}

class SocialMindWorkspace {
    constructor(api, view) { this.api = api; this.view = view; this.version = 0; this.profiles = []; }
    async open() {
        const version = ++this.version;
        this.view.reset('Consultando perfiles almacenados…');
        this.view.profiles([], true);
        try {
            const result = await this.api('/api/stored-profiles');
            if (version !== this.version) return;
            this.profiles = result.profiles;
            this.view.profiles(this.profiles, false);
            this.view.reset(this.profiles.length ? 'Selecciona un perfil almacenado.' : 'No hay perfiles almacenados en MongoDB.');
        } catch (error) { if (version === this.version) this.view.reset(error.message); }
    }
    async select(username) {
        const version = ++this.version;
        this.view.reset(username ? `Cargando @${username}…` : 'Selecciona un perfil almacenado.');
        if (!username) return;
        try {
            const data = await this.api(`/api/stored-profiles/${encodeURIComponent(username)}/publications`);
            if (version !== this.version) return;
            if (data.profile_id !== username.toLowerCase()) throw new Error('La respuesta no corresponde al perfil seleccionado.');
            const resources = await Promise.allSettled(['analysis', 'ocean'].map(kind => this.api(`/api/semantics/${encodeURIComponent(username)}/${kind}`).then(result => {
                if (result.profile_id !== username.toLowerCase()) throw new Error('La respuesta no corresponde al perfil seleccionado.');
                return result;
            })));
            if (version !== this.version) return;
            const [analysis, ocean] = resources.map(result => result.status === 'fulfilled' ? result.value : null);
            const errors = resources.map((result, index) => result.status === 'rejected' ? `${['Interpretación', 'OCEAN'][index]}: ${result.reason.message}` : '').filter(Boolean);
            this.view.render(data, this.profiles.find(profile => profile.username.toLowerCase() === username.toLowerCase()), strategicDiagnosis(data, analysis, ocean), errors);
        } catch (error) { if (version === this.version) this.view.reset(error.message); }
    }
}

function mountSocialMind() {
    const el = id => document.getElementById(id);
    const make = (tag, text) => { const node = document.createElement(tag); node.textContent = text; return node; };
    const view = {
        reset(message) { el('smResults').replaceChildren(); el('smStatus').textContent = message; },
        profiles(profiles, loading) {
            const select = el('smProfile');
            const placeholder = make('option', loading ? 'Cargando perfiles…' : 'Selecciona un perfil'); placeholder.value = '';
            select.replaceChildren(placeholder);
            profiles.forEach(profile => { const option = make('option', `${profile.nickname || profile.username} (@${profile.username})`); option.value = profile.username; select.append(option); });
            select.disabled = loading || !profiles.length;
        },
        render(data, profile, diagnosis, errors) {
            el('smStatus').textContent = `@${data.username} · ${profile?.nickname || 'Nickname no disponible'} · Datos almacenados`;
            const results = el('smResults'); results.replaceChildren();
            const node = (tag, text = '', className = '') => { const item = make(tag, text); item.className = className; return item; };
            const badge = text => node('span', text, 'tag');
            const empty = text => node('p', text, 'empty-message');
            const card = (title, description = '', className = '') => {
                const item = node('article', '', `card ${className}`);
                const header = node('div', '', 'card-heading');
                const text = node('div'); text.append(node('h3', title));
                if (description) text.append(node('p', description));
                header.append(text); item.append(header); return item;
            };
            const details = (label, children) => {
                const item = node('details', '', 'sm-details');
                item.append(node('summary', label), ...children); return item;
            };
            const shortID = id => { const text = String(id); return text.length > 12 ? `${text.slice(0, 5)}…${text.slice(-4)}` : text; };
            const publications = ids => {
                const group = node('div', '', 'sm-publications');
                [...new Set(ids || [])].forEach(id => {
                    const row = data.publications?.find(row => row.publication_id === id);
                    const url = safeVideoURL(row?.url);
                    const link = node(url ? 'a' : 'span', `${shortID(id)}${url ? ' ↗' : ''}`, 'sm-publication');
                    link.title = `${id}${url ? '' : ' · Enlace no disponible'}`;
                    if (url) { link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer'; }
                    group.append(link);
                });
                return group;
            };
            const quote = evidence => node('blockquote', `“${evidence.quote}” · ${shortID(evidence.publication_id)}`);
            // Remove equivalent repeated proposals without changing the evidence rules.
            const seen = new Set();
            const proposals = diagnosis.recommendations.filter(item => {
                if (item.title === 'Ideas desde tus temas' && diagnosis.recommendations.some(other =>
                    other.title === 'Ampliar el enfoque' && [...new Set(other.ids)].sort().join('|') === [...new Set(item.ids)].sort().join('|'))) return false;
                const key = item.text.trim().replace(/\s+/g, ' ').toLocaleLowerCase('es');
                if (seen.has(key)) return false;
                seen.add(key); return true;
            });
            errors.forEach(error => results.append(node('p', error, 'sm-notice')));
            const metrics = node('div', '', 'stats-grid sm-metrics');
            [
                ['Publicaciones disponibles', data.summary.available, '▤'],
                ['Embeddings vigentes', data.summary.generated, '◇'],
                ['Temas identificados', diagnosis.themes.length, '#'],
                ['Recomendaciones propuestas', proposals.length, '↗'],
            ].forEach(([label, value, icon]) => {
                const metric = node('div', '', 'stat-item sm-metric');
                const symbol = node('span', icon, 'stat-icon'); symbol.setAttribute('aria-hidden', 'true');
                metric.append(symbol, node('span', label, 'stat-label'), node('strong', value ?? '—')); metrics.append(metric);
            });
            results.append(metrics);
            const grid = node('div', '', 'analytics-grid sm-information');
            const themes = card('Temas principales', 'Interpretación guardada y vigente.');
            if (!diagnosis.themes.length) themes.append(empty(diagnosis.interpretation ? 'No hay temas respaldados en la interpretación.' : `Interpretación ${diagnosis.analysisStatus}. No hay temas disponibles.`));
            diagnosis.themes.forEach(theme => {
                const block = node('div', '', 'sm-theme');
                const header = node('div', '', 'sm-theme-heading');
                header.append(node('h4', theme.name), badge(`${new Set(theme.publication_ids).size} publicaciones`));
                block.append(header, details('Ver evidencias', [publications(theme.publication_ids), ...(theme.evidence || []).map(quote)]));
                themes.append(block);
            });
            const relations = card('Relaciones semánticas', 'Hasta cinco pares · Similitud coseno exacta');
            const pairs = (data.related || []).filter(pair => Number.isFinite(pair.similarity)).slice(0, 5);
            if (!pairs.length) relations.append(empty('No hay relaciones disponibles. Se necesitan al menos dos embeddings vigentes.'));
            else {
                const table = node('table', '', 'sm-relations');
                const head = node('thead'), row = node('tr');
                ['Publicación A', 'Publicación B', 'Coseno'].forEach(label => { const th = node('th', label); th.scope = 'col'; row.append(th); });
                head.append(row); const body = node('tbody');
                pairs.forEach(pair => {
                    const tr = node('tr');
                    [pair.first_publication_id, pair.second_publication_id].forEach(id => { const td = node('td'); td.append(publications([id])); tr.append(td); });
                    tr.append(node('td', pair.similarity.toFixed(4), 'sm-cosine')); body.append(tr);
                });
                table.append(head, body); relations.append(table);
            }
            relations.append(details('Cómo leer estas relaciones', [node('p', 'El coseno mide cercanía semántica, no rendimiento. Las recomendaciones consideran los pares con coseno ≥ 0,50. La tabla muestra los pares disponibles sin alterar sus valores.')]));
            grid.append(themes, relations); results.append(grid);
            const ocean = card('Presencia lingüística OCEAN', 'Señales en las publicaciones analizadas; no son puntuaciones de personalidad.', 'sm-section');
            if (!diagnosis.signals) ocean.append(empty(`Señales OCEAN no disponibles: ${diagnosis.oceanStatus}.`));
            else if (diagnosis.signals.partial) ocean.append(badge('Análisis parcial'));
            const oceanGrid = node('div', '', 'sm-ocean-grid');
            Object.entries({openness: 'Apertura', conscientiousness: 'Responsabilidad', extraversion: 'Extraversión', agreeableness: 'Amabilidad', neuroticism: 'Neuroticismo'}).forEach(([key, label]) => {
                const dimension = diagnosis.signals?.dimensions?.find(row => row.dimension === key);
                const support = dimension?.support_count, total = dimension?.total_count;
                const valid = Number.isInteger(support) && Number.isInteger(total) && total > 0 && support >= 0 && support <= total;
                // Same presence calculation used by the existing Big Five view.
                const percent = valid ? Math.round(support / total * 1000) / 10 : null;
                const item = node('article', '', 'sm-ocean-card');
                const state = !valid ? 'Sin datos disponibles' : support === 0 ? 'Sin señales identificadas' : support === 1 ? 'Señal aislada' : 'Señales observadas';
                item.append(node('h4', label), node('strong', valid ? `${percent} %` : '—', 'sm-ocean-number'));
                const meter = node('div', '', 'sm-meter'); meter.setAttribute('aria-hidden', 'true');
                const fill = node('span'); fill.style.width = `${percent ?? 0}%`; meter.append(fill);
                item.append(meter, node('small', valid ? `${support} de ${total} publicaciones con señales` : 'Sin conteos guardados'), node('p', state, 'sm-ocean-state'));
                const evidence = [];
                if (dimension?.description) evidence.push(node('p', dimension.description));
                (dimension?.indicators || []).forEach(indicator => {
                    const block = node('div', '', 'sm-signal');
                    block.append(node('h4', indicator.name), node('p', indicator.description), publications(indicator.publication_ids));
                    (indicator.evidence || []).forEach(item => block.append(quote(item)));
                    evidence.push(block);
                });
                item.append(details('Ver evidencias', evidence.length ? evidence : [empty('Sin indicadores respaldados disponibles.')])); oceanGrid.append(item);
            });
            ocean.append(oceanGrid); results.append(ocean);
            const recommendations = node('section', '', 'sm-section');
            recommendations.append(node('h3', 'Recomendaciones estratégicas'));
            const recommendationGrid = node('div', '', 'sm-recommendation-grid');
            proposals.forEach(item => {
                const recommendation = card(item.title || 'Propuesta estratégica', '', 'sm-recommendation');
                recommendation.append(badge(item.type || 'Contenido'), node('p', item.text, 'sm-recommendation-text'));
                const ids = [...new Set(item.ids || [])];
                const basis = item.title === 'Completar la cobertura' ? `${data.summary.pending} publicaciones con embeddings pendientes.`
                    : item.title === 'Reforzar la evidencia' ? `${data.summary.available} publicaciones, ${diagnosis.themes.length} temas y ${diagnosis.related.length} pares con coseno ≥ 0,50.`
                    : item.title === 'Explorar conexiones' ? `${diagnosis.related.length} pares con coseno ≥ 0,50.`
                    : `${ids.length} publicaciones respaldan el tema.`;
                recommendation.append(node('p', `Sustento: ${basis}`, 'sm-basis'));
                recommendation.append(details('Ver publicaciones de respaldo', ids.length ? [publications(ids)] : [empty('Esta recomendación se basa en la cobertura del conjunto, sin publicaciones individuales de respaldo.')]));
                recommendationGrid.append(recommendation);
            });
            if (!proposals.length) recommendationGrid.append(empty('No hay recomendaciones sustentadas adicionales con los datos disponibles.'));
            recommendations.append(recommendationGrid); results.append(recommendations);
            const final = card('Resumen estratégico', '', 'sm-section');
            const insufficient = data.summary.available < 2 || (!diagnosis.themes.length && !diagnosis.related.length);
            final.append(node('p', `${data.summary.available} publicaciones disponibles, ${diagnosis.themes.length} temas respaldados y ${diagnosis.related.length} relaciones con coseno ≥ 0,50. ${insufficient ? 'La evidencia es insuficiente para una estrategia de contenido; conviene reunir información adicional autorizada.' : `Hay ${proposals.length} propuestas para revisar a partir de los temas y relaciones disponibles.`}`));
            final.append(node('p', 'Este diagnóstico describe el contenido guardado y no predice crecimiento ni resultados comerciales.', 'sm-helper'));
            final.append(details('Cobertura y límites del diagnóstico', [node('p', `Embeddings pendientes: ${data.summary.pending ?? 'sin dato'}. Publicaciones sin texto: ${data.summary.empty ?? 'sin dato'}. Interpretación: ${diagnosis.interpretation ? (diagnosis.interpretation.partial ? 'vigente y parcial' : 'vigente') : diagnosis.analysisStatus}. OCEAN: ${diagnosis.signals ? (diagnosis.signals.partial ? 'vigente y parcial' : 'vigente') : diagnosis.oceanStatus}.`), node('p', 'Interpretación y OCEAN abarcan hasta 10 publicaciones. Solo se utilizan análisis vigentes. Presencia lingüística = publicaciones con señales / publicaciones analizadas × 100. Las recomendaciones aplican reglas locales; no se generan nuevos análisis.')]));
            results.append(final);
        },
    };
    const workspace = new SocialMindWorkspace(path => storedRequest(path, {method: 'GET'}), view);
    el('smProfile').addEventListener('change', event => workspace.select(event.target.value));
    el('smRefresh').addEventListener('click', () => workspace.open());
    return workspace;
}
if (typeof module !== 'undefined') module.exports = {strategicDiagnosis, SocialMindWorkspace};
if (typeof document !== 'undefined') window.socialMind = mountSocialMind();

'use strict';

class ResearchWorkspace {
    constructor(api, view, schedule = (callback, delay) => setTimeout(callback, delay), unschedule = id => clearTimeout(id)) {
        this.api = api; this.view = view; this.schedule = schedule; this.unschedule = unschedule;
        this.version = 0; this.selected = null; this.timer = null; this.visible = false;
        this.offset = 0; this.recordsOffset = 0; this.busy = false;
    }
    close() { this.visible = false; ++this.version; this.unschedule(this.timer); }
    async open() {
        this.close(); this.visible = true;
        const version = this.version;
        this.view.message('Consultando investigaciones. El trabajador se ejecuta por separado.');
        try {
            const capabilities = await this.api('/api/research/sources');
            if (version !== this.version) return;
            this.view.capabilities(capabilities);
            await this.list();
        } catch (error) { if (version === this.version) this.view.message(error.message); }
    }
    async list(offset = this.offset) {
        const version = this.version;
        const data = await this.api(`/api/research/studies?offset=${offset}&limit=20`);
        if (version !== this.version) return;
        if (this.selected && !data.studies.some(study => study.study_id === this.selected)) {
            this.selected = null; this.unschedule(this.timer); this.view.clear();
        }
        this.offset = offset; this.view.list(data, this.selected);
        this.view.message(data.total ? 'Selecciona una investigación y comprueba su fuente.' : 'No hay investigaciones. Crea una con cualquier tema.');
        if (this.selected) await this.select(this.selected);
    }
    async create(payload) {
        if (this.busy) return;
        this.busy = true; this.view.busy(true);
        const version = this.version;
        try {
            const study = await this.api('/api/research/studies', {method: 'POST', body: JSON.stringify(payload)});
            if (version !== this.version) return;
            this.selected = study.study_id; this.offset = 0;
            await this.list(0);
        } catch (error) { if (version === this.version) this.view.message(error.message); }
        finally { this.busy = false; this.view.busy(false); }
    }
    async select(identity) {
        ++this.version; this.unschedule(this.timer);
        this.selected = identity || null; this.recordsOffset = 0;
        this.view.clear();
        if (this.selected) await this.refresh(this.version);
    }
    async refresh(version = this.version) {
        try {
            const identity = this.selected;
            const study = await this.api(`/api/research/studies/${identity}/progress`);
            if (version !== this.version || study.study_id !== this.selected) return;
            this.view.study(study); await this.records(this.recordsOffset, version);
            if (version !== this.version) return;
            if (this.visible && ['queued', 'discovering', 'acquiring'].includes(study.status)) {
                this.unschedule(this.timer);
                this.timer = this.schedule(() => this.refresh(version), 1500);
            }
        } catch (error) {
            if (version === this.version) this.view.message(error.message + ' Usa Actualizar para reintentar.');
        }
    }
    async action(action) {
        if (!this.selected || this.busy) return;
        this.busy = true; this.view.busy(true);
        this.unschedule(this.timer);
        const version = ++this.version;
        try {
            const study = await this.api(`/api/research/studies/${this.selected}/${action}`, {method: 'POST'});
            if (version !== this.version || study.study_id !== this.selected) return;
            await this.refresh(version);
        } catch (error) { if (version === this.version) this.view.message(error.message); }
        finally { this.busy = false; this.view.busy(false); }
    }
    async records(offset = 0, version = this.version) {
        if (!this.selected) return;
        try {
            const result = await this.api(`/api/research/studies/${this.selected}/records?offset=${offset}&limit=25`);
            if (version !== this.version) return;
            this.recordsOffset = offset; this.view.records(result);
        } catch (error) { if (version === this.version) this.view.message(error.message); }
    }
}

async function researchRequest(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json'}, signal: controller.signal});
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Revisa el tema, objetivo y límites de la solicitud.');
        return result;
    } catch (error) {
        if (error.name === 'AbortError') throw new Error('La consulta tardó demasiado. Consulta el estado antes de repetir una creación.');
        throw error;
    } finally { clearTimeout(timer); }
}

function researchErrorMessage(code) {
    const messages = {
        source_structure_changed: 'No se reconocieron los resultados de TikTok. Revisa el diagnóstico del trabajador.',
        source_load_timeout: 'TikTok no terminó de cargar los resultados dentro del tiempo permitido. Revisa el diagnóstico del trabajador.',
        access_restricted: 'TikTok mostró una restricción de acceso. Revisa el diagnóstico del trabajador.',
        browser_unavailable: 'El navegador no pudo iniciar o completar la carga. Revisa el diagnóstico del trabajador.',
        checkpoint_changed: 'Los resultados cambiaron respecto al checkpoint. Revisa el diagnóstico del trabajador.',
    };
    return messages[code] || code || '—';
}

function researchRecordLabels(records, studySynthetic) {
    const neutral = {heading: 'Registros preparados', publication: 'Publicación'};
    if (!records.length) return neutral;
    const provenance = records[0]?.synthetic;
    if (typeof provenance !== 'boolean' || records.some(record => record?.synthetic !== provenance)
        || (typeof studySynthetic === 'boolean' && studySynthetic !== provenance)) return neutral;
    return provenance
        ? {heading: 'Registros sintéticos · Datos de prueba — No reales', publication: 'Publicación sintética'}
        : {heading: 'Registros recopilados', publication: 'Publicación'};
}

function mountResearch() {
    const el = id => document.getElementById(id);
    const make = (tag, text = '', className = '') => {
        const node = document.createElement(tag); node.textContent = text; node.className = className; return node;
    };
    const labels = {draft: 'Creada · sin iniciar', queued: 'En cola · requiere trabajador', discovering: 'Descubriendo publicaciones',
        acquiring: 'Preparando registros', paused: 'Pausada', target_reached: 'Objetivo alcanzado',
        exhausted: 'Recorrido disponible finalizado', partial: 'Resultado parcial con fallos', failed: 'Procesamiento fallido', cancelled: 'Cancelada'};
    let current = null, busy = false;
    function recordLabels(records = []) {
        const labels = researchRecordLabels(records, current?.synthetic);
        el('researchRecordsHeading').textContent = labels.heading;
        el('researchPublicationHeader').textContent = labels.publication;
    }
    function buttons() {
        const state = current?.status;
        const allowed = {start: ['draft'], pause: ['queued', 'discovering', 'acquiring'], resume: ['paused'], cancel: ['draft', 'queued', 'discovering', 'acquiring', 'paused']};
        document.querySelectorAll('#research [data-research-action]').forEach(button => { button.disabled = busy || !allowed[button.dataset.researchAction].includes(state); });
        el('researchCreate').disabled = busy;
    }
    function sourceChanged() {
        const source = el('researchSource').value;
        el('researchSyntheticConfig').hidden = source !== 'synthetic';
        el('researchYouTubeConfig').hidden = source !== 'youtube';
        el('researchTikTokConfig').hidden = source !== 'tiktok';
        el('researchSourceLabel').textContent = source === 'youtube' ? 'YouTube Data API v3 · Datos reales al iniciar el trabajador' : source === 'tiktok' ? 'TikTok · Playwright · Adquisición externa sujeta a habilitación' : 'Datos de prueba — No reales';
    }
    el('researchSource').addEventListener('change', sourceChanged);
    const view = {
        message(text) { el('researchStatus').textContent = text; },
        capabilities(data) {
            el('researchTarget').max = data.max_target_records;
            el('researchSource').replaceChildren(...(data.sources || [{source: 'synthetic', source_label: data.source_label, available: true}]).map(source => {
                const option = make('option', source.source_label + (source.reason ? ` · ${source.reason}` : ''));
                option.value = source.source; option.disabled = !source.available; return option;
            }));
            sourceChanged();
        },
        busy(value) { busy = value; buttons(); },
        clear() { current = null; el('researchDetail').hidden = true; el('researchRows').replaceChildren(); recordLabels(); buttons(); },
        list(data, selected) {
            const placeholder = make('option', 'Selecciona una investigación'); placeholder.value = '';
            const select = el('researchSelect'); select.replaceChildren(placeholder);
            data.studies.forEach(study => { const option = make('option', `${study.topic} · ${labels[study.status]}`); option.value = study.study_id; select.append(option); });
            select.value = selected || ''; select.disabled = !data.studies.length;
            el('researchListPrevious').disabled = !data.offset;
            el('researchListNext').disabled = data.offset + data.limit >= data.total;
            el('researchListCount').textContent = `${data.total} investigaciones · página ${Math.floor(data.offset / 20) + 1}`;
        },
        study(study) {
            current = study; el('researchDetail').hidden = false;
            el('researchHeading').textContent = study.topic;
            el('researchDescriptionText').textContent = study.description;
            el('researchState').textContent = labels[study.status] || study.status;
            el('researchProgress').value = study.counters.prepared; el('researchProgress').max = study.target_records;
            el('researchProgressText').textContent = `${study.counters.prepared} / ${study.target_records} preparados (${study.progress_percent} % del objetivo)`;
            const c = study.counters;
            const facts = [['Preparados', c.prepared], ['Excluidos', c.excluded], ['Duplicados detectados', c.duplicates],
                ['Recibidos', c.received], ['Publicaciones descubiertas', c.publications_discovered], ['Publicaciones procesadas', c.publications_processed],
                ['Tareas pendientes', study.pending_tasks], ['Tareas fallidas', study.failed_tasks], ['Lotes guardados', c.batches],
                ['Duración activa (s)', c.processing_seconds.toFixed(3)]];
            el('researchFacts').replaceChildren(...facts.map(([label, value]) => { const node = make('div', '', 'research-fact'); node.append(make('span', label), make('strong', value)); return node; }));
            el('researchActivity').textContent = `Última actividad: ${study.updated_at} · Motivo: ${study.stop_reason || '—'} · Último error: ${study.source === 'tiktok' ? researchErrorMessage(study.last_error) : study.last_error || '—'}`;
            el('researchWarnings').replaceChildren(...study.warnings.map(warning => make('p', warning)));
            this.message(`${labels[study.status]} · ${study.source_label}. ${study.source === 'tiktok' && study.last_error ? researchErrorMessage(study.last_error) + ' ' : ''}El progreso corresponde al objetivo, no a una plataforma externa.`);
            buttons();
        },
        records(data) {
            recordLabels(data.records);
            el('researchRows').replaceChildren(...data.records.map(record => {
                const row = make('tr'); row.append(make('td', record.publication_id), make('td', record.text), make('td', record.redactions)); return row;
            }));
            el('researchRecordsCount').textContent = `${data.total} registros preparados · ${data.records.length ? data.offset + 1 : 0}–${data.offset + data.records.length}`;
            el('researchRecordsPrevious').disabled = !data.offset;
            el('researchRecordsNext').disabled = data.offset + data.limit >= data.total;
        },
    };
    const workspace = new ResearchWorkspace(researchRequest, view);
    el('researchForm').addEventListener('submit', event => {
        event.preventDefault();
        workspace.create({topic: el('researchTopic').value, description: el('researchDescription').value,
            source: el('researchSource').value, target_records: Number(el('researchTarget').value),
            limits: {batch_size: Number(el('researchBatch').value)},
            source_config: el('researchSource').value === 'tiktok' ? {max_publications: Number(el('researchTikTokVideos').value), max_comments_per_publication: Number(el('researchTikTokComments').value), max_scrolls: Number(el('researchTikTokScrolls').value)} : el('researchSource').value === 'youtube' ? {max_publications: Number(el('researchYouTubeVideos').value), max_pages_per_publication: Number(el('researchYouTubePages').value), include_replies: el('researchReplies').checked, published_after: el('researchAfter').value ? el('researchAfter').value + 'T00:00:00Z' : null, published_before: el('researchBefore').value ? el('researchBefore').value + 'T00:00:00Z' : null} : {publications: Number(el('researchPublications').value), comments_per_publication: Number(el('researchComments').value),
                            failure_mode: el('researchFailure').value}});
    });
    el('researchSelect').addEventListener('change', event => workspace.select(event.target.value));
    el('researchRefresh').addEventListener('click', () => workspace.open());
    el('researchListPrevious').addEventListener('click', () => workspace.list(Math.max(0, workspace.offset - 20)).catch(error => view.message(error.message)));
    el('researchListNext').addEventListener('click', () => workspace.list(workspace.offset + 20).catch(error => view.message(error.message)));
    el('researchRecordsPrevious').addEventListener('click', () => workspace.records(Math.max(0, workspace.recordsOffset - 25)));
    el('researchRecordsNext').addEventListener('click', () => workspace.records(workspace.recordsOffset + 25));
    document.querySelectorAll('#research [data-research-action]').forEach(button => button.addEventListener('click', () => workspace.action(button.dataset.researchAction)));
    buttons(); return workspace;
}

if (typeof module !== 'undefined') module.exports = {researchErrorMessage, researchRecordLabels, ResearchWorkspace};
if (typeof document !== 'undefined') window.research = mountResearch();

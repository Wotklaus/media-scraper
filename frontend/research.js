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
            if (this.view.analysis) await this.analysis(false, version);
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
    async analysis(generate = false, version = this.version) {
        const identity = this.selected;
        if (!identity || !this.view.analysis) return;
        if (generate && this.analysisBusy) return;
        if (generate) { this.analysisBusy = true; this.view.analysisBusy?.(true); }
        try {
            const data = await this.api(`/api/research/studies/${identity}/analysis`, generate ? {method: 'POST'} : {}, 180000);
            if (version === this.version && identity === this.selected) this.view.analysis(data);
        } catch (error) {
            if (version === this.version && identity === this.selected) this.view.analysis({status: 'failed', failure: {message: error.message}});
        } finally {
            if (generate) { this.analysisBusy = false; this.view.analysisBusy?.(false); }
        }
    }
}

async function researchRequest(path, options = {}, timeout = 15000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
        const response = await fetch(path, {...options, headers: {'Content-Type': 'application/json'}, signal: controller.signal});
        const result = await response.json();
        if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : result.detail?.message || 'Revisa el tema, objetivo y límites de la solicitud.');
        return result;
    } catch (error) {
        if (error.name === 'AbortError') throw new Error(path.endsWith('/analysis') ? 'El análisis tardó demasiado. Consulta el análisis guardado antes de reintentarlo.' : 'La consulta tardó demasiado. Consulta el estado antes de repetir una creación.');
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
    let current = null, busy = false, analysisBusy = false, analysisStatus = null, analysisEligible = false;
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
        const eligible = analysisEligible && ['exhausted', 'target_reached', 'partial'].includes(state);
        el('researchAnalyze').disabled = !eligible || analysisBusy || analysisStatus === 'processing' || analysisStatus === 'completed';
        el('researchAnalysisRefresh').disabled = !eligible || analysisBusy;
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
        clear() { current = null; analysisStatus = null; analysisEligible = false; el('researchDetail').hidden = true; el('researchRows').replaceChildren(); recordLabels();
            el('researchAnalyze').textContent = 'Analizar comentarios';
            el('researchAnalysisIntro').textContent = 'Selecciona una investigación finalizada para consultar sus comentarios. El análisis envía los textos preparados a OpenAI y puede generar un costo. No realiza nuevas búsquedas.';
            el('researchAnalysisResults').replaceChildren(); el('researchAnalysisStatus').textContent = 'Selecciona la investigación para consultar su análisis.'; buttons(); },
        analysisBusy(value) { analysisBusy = value; if (value) el('researchAnalysisStatus').textContent = 'Analizando comentarios… No cierres el servidor. Puedes consultar el resultado guardado al finalizar.'; buttons(); },
        analysis(data) {
            analysisStatus = data.status;
            if (typeof data.eligible === 'boolean') analysisEligible = data.eligible;
            if (Number.isInteger(data.comment_count)) {
                el('researchAnalyze').textContent = `Analizar ${data.comment_count} comentarios`;
                el('researchAnalysisIntro').textContent = `${current?.topic || 'Investigación'} · ${data.comment_count} comentarios preparados para análisis. El análisis envía sus textos a OpenAI y puede generar un costo. No realiza nuevas búsquedas.`;
            }
            const container = el('researchAnalysisResults'); container.replaceChildren();
            const states = {unavailable: 'No hay análisis disponible.', stale: 'El análisis anterior no corresponde al contenido actual. Puedes ejecutar uno nuevo.',
                processing: 'Análisis en proceso. Consulta el análisis guardado en unos momentos; no se inicia otra solicitud.',
                failed: 'No se pudo completar el análisis.', completed: 'Análisis automático guardado. Las categorías son propuestas sin validación humana.'};
            el('researchAnalysisStatus').textContent = data.message || data.failure?.message || states[data.status] || 'Estado de análisis desconocido.';
            buttons();
            if (data.status !== 'completed' || !data.result) return;
            const result = data.result;
            const categories = {technical_question: 'Dudas técnicas', general_question: 'Preguntas generales', commercial_request: 'Solicitudes comerciales', social_opinion: 'Opiniones sociales', insufficient_context: 'Contexto insuficiente'};
            container.append(make('p', `${data.embedding_model} · ${data.model} · ${data.generated_at}`));
            container.append(make('p', `${result.comments.length} comentarios · ${result.ambiguous_count} ambiguos. Agrupación exploratoria por coseno, umbral ${data.grouping.threshold}; sin calibración manual.`));
            (result.validation_warnings || []).forEach(warning => container.append(make('p', warning)));
            const counts = make('ul');
            Object.entries(result.category_counts).forEach(([key, count]) => counts.append(make('li', `${categories[key] || key}: ${count}`)));
            container.append(make('h4', 'Categorías propuestas'), counts);
            const lookup = new Map(result.comments.map(comment => [comment.record_key, comment]));
            function evidence(keys) {
                const details = make('details'); details.append(make('summary', `Ver ${keys.length} comentarios de respaldo`));
                keys.forEach(key => {
                    const comment = lookup.get(key); if (!comment) return;
                    details.append(make('p', `${key.slice(0, 8)} · ${categories[comment.category]} · ${comment.publication_id} · ${comment.source || 'fuente no disponible'}${comment.synthetic === true ? ' · Datos sintéticos' : ''}`),
                        make('blockquote', comment.text), make('p', `Cita verificada: «${comment.quote}». ${comment.reason}${comment.ambiguous ? ' · Ambiguo; alternativas: ' + comment.alternatives.map(c => categories[c]).join(', ') : ''}`));
                });
                return details;
            }
            container.append(evidence(result.comments.map(c => c.record_key)), make('h4', 'Grupos por similitud semántica'));
            result.groups.forEach(group => container.append(make('p', `${group.title} · ${group.count} comentarios · ${group.publication_count} publicaciones`), evidence(group.record_keys)));
            container.append(make('h4', 'Necesidades, preguntas frecuentes, temas y tendencias'));
            const kinds = {need: 'Necesidad', faq: 'Pregunta frecuente', theme: 'Tema o tendencia exploratoria'};
            if (!result.findings.length) container.append(make('p', 'No se obtuvieron hallazgos respaldados.'));
            result.findings.forEach(finding => container.append(make('p', `${kinds[finding.kind]}: ${finding.title} · ${finding.count} comentarios · ${finding.publication_count} publicaciones`), evidence(finding.record_keys)));
            container.append(make('h4', 'Recomendaciones de aprendizaje'), make('p', 'Se han verificado las citas de respaldo, no la eficacia pedagógica. Las actividades requieren revisión educativa; no hay enlaces, cursos ni certificaciones verificados.'));
            if (!result.recommendations.length) container.append(make('p', 'No se generaron recomendaciones con respaldo suficiente.'));
            result.recommendations.forEach(item => container.append(make('p', item.activity + ' · Pendiente de revisión educativa'), evidence(item.record_keys)));
        },
        list(data, selected) {
            const placeholder = make('option', 'Selecciona una investigación'); placeholder.value = '';
            const select = el('researchSelect'); select.replaceChildren(placeholder);
            data.studies.forEach(study => { const option = make('option', `${study.topic} · ${labels[study.status]} · ${study.study_id.slice(0, 8)}`); option.value = study.study_id; select.append(option); });
            select.value = selected || ''; select.disabled = !data.studies.length;
            el('researchListPrevious').disabled = !data.offset;
            el('researchListNext').disabled = data.offset + data.limit >= data.total;
            el('researchListCount').textContent = `${data.total} investigaciones · página ${Math.floor(data.offset / 20) + 1}`;
        },
        study(study) {
            current = study; el('researchDetail').hidden = false;
            el('researchHeading').textContent = study.topic;
            el('researchAnalysisIntro').textContent = `${study.topic} · consultando comentarios preparados. El análisis envía sus textos a OpenAI y puede generar un costo. No realiza nuevas búsquedas.`;
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
    el('researchAnalyze').addEventListener('click', () => workspace.analysis(true));
    el('researchAnalysisRefresh').addEventListener('click', () => workspace.analysis());
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

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
    let recordsPage = null, modalEntries = [], modalMode = null, modalTrigger = null, groupPage = 0;
    const categoryNames = {technical_question: 'Dudas técnicas', general_question: 'Preguntas generales', commercial_request: 'Solicitudes comerciales', social_opinion: 'Opiniones sociales', insufficient_context: 'Contexto insuficiente'};
    const svgPaths = {publication: 'M4 5h16v14H4z M8 9h8 M8 13h6', comment: 'M4 5h16v12H9l-5 3z M8 10h8', chart: 'M4 19V5 M8 16v-4 M13 16V8 M18 16V5', spark: 'M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z'};
    function icon(name) {
        const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
        svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true'); svg.classList.add('research-icon');
        const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
        path.setAttribute('d', svgPaths[name] || svgPaths.chart); path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'currentColor');
        path.setAttribute('stroke-width', '1.7'); path.setAttribute('stroke-linecap', 'round'); path.setAttribute('stroke-linejoin', 'round'); svg.append(path); return svg;
    }
    function metric(label, value, name, note = '') {
        const card = make('div', '', 'research-metric'); const heading = make('span', '', 'research-metric-label');
        heading.append(icon(name), document.createTextNode(label)); card.append(heading, make('strong', String(value)));
        if (note) card.append(make('small', note)); return card;
    }
    function tab(name) {
        document.querySelectorAll('#research [data-research-tab]').forEach(button => {
            const selected = button.dataset.researchTab === name; button.setAttribute('aria-selected', String(selected));
            el('researchPanel' + button.dataset.researchTab[0].toUpperCase() + button.dataset.researchTab.slice(1)).hidden = !selected;
        });
    }
    function recordLabels(records = []) {
        const labels = researchRecordLabels(records, current?.synthetic);
        el('researchRecordsHeading').textContent = labels.heading;
    }
    function renderModal() {
        const query = el('researchDialogSearch').value.trim().toLocaleLowerCase();
        const visible = modalEntries.filter(entry => `${entry.text || ''} ${entry.publication_id || ''}`.toLocaleLowerCase().includes(query));
        const root = el('researchDialogItems'); root.replaceChildren();
        visible.forEach(entry => {
            const card = make('article', '', 'research-evidence-card');
            const heading = make('div', '', 'research-evidence-meta');
            heading.append(make('strong', entry.publication_id || 'Publicación no disponible'),
                make('span', `${entry.source || current?.source || 'Fuente no disponible'} · ${entry.synthetic === true ? 'Sintético' : entry.synthetic === false ? 'Recopilado' : 'Procedencia no disponible'}`));
            card.append(heading, make('p', entry.text || 'Texto no disponible'));
            if (entry.quote) card.append(make('blockquote', entry.quote), make('small', `Cita verificada · ${entry.reason || ''}`));
            if (entry.ambiguous) card.append(make('small', `Clasificación ambigua${entry.alternatives?.length ? ' · alternativas: ' + entry.alternatives.map(item => categoryNames[item] || item).join(', ') : ''}`));
            root.append(card);
        });
        if (!visible.length) root.append(make('p', 'No hay comentarios en esta vista para el filtro escrito.', 'research-muted'));
        el('researchDialogCount').textContent = `${visible.length} de ${modalEntries.length} comentarios en esta vista${modalMode === 'records' ? ' · solo esta página' : ''}`;
        el('researchRecordsPrevious').hidden = modalMode !== 'records'; el('researchRecordsNext').hidden = modalMode !== 'records';
        if (modalMode === 'records' && recordsPage) {
            el('researchRecordsPrevious').disabled = !recordsPage.offset;
            el('researchRecordsNext').disabled = recordsPage.offset + recordsPage.limit >= recordsPage.total;
        }
    }
    function showModal(title, entries, mode, trigger) {
        modalMode = mode; modalEntries = entries; modalTrigger = trigger || document.activeElement;
        el('researchDialogTitle').textContent = title;
        el('researchDialogSummary').textContent = mode === 'records' ? 'Registros preparados · navegación paginada' : 'Evidencias del análisis guardado · citas vinculadas a comentarios del estudio';
        el('researchDialogSearch').value = ''; renderModal();
        const dialog = el('researchEvidenceDialog'); if (!dialog.open) dialog.showModal();
        el('researchDialogSearch').focus();
    }
    function renderAnalysis(data) {
        const result = data.result, root = el('researchAnalysisResults'); root.replaceChildren();
        groupPage = 0;
        const lookup = new Map(result.comments.map(comment => [comment.record_key, comment]));
        const evidenceButton = (keys, title) => {
            const button = make('button', `Ver ${keys.length} evidencias`, 'research-link-button'); button.type = 'button';
            button.disabled = !keys.length;
            button.addEventListener('click', () => showModal(title, keys.map(key => lookup.get(key)).filter(Boolean), 'evidence', button));
            return button;
        };
        const overview = make('article', '', 'card research-dashboard-card');
        overview.append(make('span', 'PANORAMA DEL ANÁLISIS', 'research-eyebrow'), make('h3', 'Resumen analítico'));
        const summary = make('div', '', 'research-metric-grid');
        summary.append(metric('Comentarios analizados', result.comments.length, 'comment'),
            metric('Categorías presentes', Object.values(result.category_counts).filter(Boolean).length, 'chart'),
            metric('Casos ambiguos', result.ambiguous_count, 'spark'),
            metric('Grupos', result.groups.length, 'publication'),
            metric('Hallazgos', result.findings.length, 'chart'),
            metric('Cobertura del estudio', `${result.comments.length} / ${current?.counters?.prepared ?? data.comment_count ?? result.comments.length}`, 'comment', 'Analizados / preparados'));
        overview.append(summary, make('p', `${data.embedding_model} · ${data.model} · ${data.generated_at} · agrupación exploratoria, coseno mínimo ${data.grouping?.threshold ?? 'no disponible'}. Las categorías no tienen validación humana.`, 'research-muted'));
        (result.validation_warnings || []).forEach(warning => overview.append(make('p', warning, 'research-note-warning')));
        root.append(overview);

        const classification = make('article', '', 'card research-dashboard-card');
        classification.append(make('span', 'CLASIFICACIÓN AUTOMÁTICA', 'research-eyebrow'), make('h3', 'Distribución de comentarios'),
            make('p', 'Porcentajes calculados sobre los comentarios analizados; cada barra representa una categoría propuesta.', 'research-muted'));
        const bars = make('div', '', 'research-bars');
        Object.entries(result.category_counts).forEach(([key, count]) => {
            const keys = result.comments.filter(comment => comment.category === key).map(comment => comment.record_key);
            const row = make('div', '', 'research-bar-row'), head = make('div', '', 'research-bar-head');
            const percent = result.comments.length ? Math.round(count / result.comments.length * 100) : 0;
            head.append(make('strong', categoryNames[key] || key), make('span', `${count} · ${percent} %`));
            const track = make('div', '', 'research-bar-track'), fill = make('span', '', 'research-bar-fill');
            fill.style.width = `${percent}%`; track.append(fill); row.append(head, track, evidenceButton(keys, categoryNames[key] || key)); bars.append(row);
        });
        classification.append(bars); root.append(classification);

        const groupsCard = make('article', '', 'card research-dashboard-card');
        const groupHead = make('div', '', 'research-section-head');
        const groupTitle = make('div'); groupTitle.append(make('span', 'EMBEDDINGS Y SIMILITUD', 'research-eyebrow'), make('h3', 'Grupos semánticos'));
        groupHead.append(groupTitle, make('span', `${result.groups.filter(group => group.count > 1).length} grupos de varios comentarios · ${result.groups.filter(group => group.count === 1).length} individuales`, 'research-soft-badge'));
        groupsCard.append(groupHead, make('p', 'Tamaños y similitud mínima de los integrantes de cada grupo. No se calculan coordenadas ni distancias entre grupos.', 'research-muted'));
        const groupList = make('div', '', 'research-card-grid'), groupControls = make('div', '', 'research-pager');
        const groupPageSize = window.matchMedia('(max-width: 560px)').matches ? 4 : 8;
        function renderGroups() {
            groupList.replaceChildren(); groupControls.replaceChildren();
            result.groups.slice(groupPage * groupPageSize, groupPage * groupPageSize + groupPageSize).forEach(group => {
                const card = make('div', '', 'research-small-card');
                card.append(make('span', group.count > 1 ? 'GRUPO RELACIONADO' : 'CASO INDIVIDUAL', 'research-eyebrow'),
                    make('h4', group.title), make('p', `${group.count} comentarios · ${group.publication_count} publicaciones`, 'research-muted'),
                    make('p', group.minimum_similarity == null ? 'Sin similitud interna calculable' : `Coseno mínimo interno: ${Number(group.minimum_similarity).toFixed(2)}`, 'research-muted'),
                    evidenceButton(group.record_keys, group.title)); groupList.append(card);
            });
            if (result.groups.length > groupPageSize) {
                const previous = make('button', 'Anterior', 'research-link-button'); previous.type = 'button'; previous.disabled = groupPage === 0;
                previous.addEventListener('click', () => { groupPage--; renderGroups(); });
                const next = make('button', 'Siguiente', 'research-link-button'); next.type = 'button'; next.disabled = (groupPage + 1) * groupPageSize >= result.groups.length;
                next.addEventListener('click', () => { groupPage++; renderGroups(); });
                groupControls.append(previous, make('span', `Página ${groupPage + 1} de ${Math.ceil(result.groups.length / groupPageSize)}`), next);
            }
        }
        renderGroups(); groupsCard.append(groupList, groupControls); root.append(groupsCard);

        const findingsCard = make('article', '', 'card research-dashboard-card');
        findingsCard.append(make('span', 'NECESIDADES Y PATRONES', 'research-eyebrow'), make('h3', 'Hallazgos exploratorios'),
            make('p', 'Respaldados por comentarios observados; no representan a toda la población.', 'research-muted'));
        const findings = make('div', '', 'research-card-grid');
        const kinds = {need: 'Necesidad educativa', faq: 'Pregunta frecuente', theme: 'Tema o tendencia'};
        result.findings.forEach(item => { const card = make('div', '', 'research-small-card');
            card.append(make('span', kinds[item.kind] || item.kind, 'research-eyebrow'), make('h4', item.title),
                make('p', `${item.count} comentarios · ${item.publication_count} publicaciones`, 'research-muted'), evidenceButton(item.record_keys, item.title)); findings.append(card); });
        if (!result.findings.length) findings.append(make('p', 'No se encontraron hallazgos con respaldo suficiente.', 'research-muted'));
        findingsCard.append(findings); root.append(findingsCard);

        const recCard = make('article', '', 'card research-dashboard-card');
        recCard.append(make('span', 'SIGUIENTES PASOS', 'research-eyebrow'), make('h3', 'Recomendaciones de aprendizaje'),
            make('p', 'Solo hay actividades propuestas. No existen artículos, cursos o certificaciones verificados para este estudio.', 'research-muted'));
        const recs = make('div', '', 'research-card-grid');
        result.recommendations.forEach(item => { const card = make('div', '', 'research-small-card research-recommendation');
            const heading = make('span', 'ACTIVIDAD DE APRENDIZAJE', 'research-eyebrow'); heading.prepend(icon('spark'));
            card.append(heading, make('h4', item.activity), make('p', 'Pendiente de revisión educativa', 'research-review'),
                make('p', `${item.count} comentarios de respaldo`, 'research-muted'), evidenceButton(item.record_keys, item.activity)); recs.append(card); });
        if (!result.recommendations.length) recs.append(make('p', 'No hay actividades con respaldo suficiente.', 'research-muted'));
        recCard.append(recs); root.append(recCard);
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
        if (!current) el('researchSourceLabel').textContent = source === 'youtube' ? 'YouTube Data API v3 · Datos reales al iniciar el trabajador' : source === 'tiktok' ? 'TikTok · Playwright · Adquisición externa sujeta a habilitación' : 'Datos de prueba — No reales';
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
        clear() { current = null; recordsPage = null; analysisStatus = null; analysisEligible = false; el('researchDetail').hidden = true;
            el('researchForm').hidden = false; el('researchNewStudy').textContent = 'Nueva investigación';
            sourceChanged();
            if (el('researchEvidenceDialog').open) el('researchEvidenceDialog').close(); modalMode = null; modalEntries = []; tab('acquisition'); recordLabels();
            el('researchExploreRecords').disabled = true;
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
            el('researchAnalysisResults').replaceChildren();
            const states = {unavailable: 'No hay análisis disponible.', stale: 'El análisis anterior no corresponde al contenido actual. Puedes ejecutar uno nuevo.',
                processing: 'Análisis en proceso. Consulta el análisis guardado en unos momentos; no se inicia otra solicitud.',
                failed: 'No se pudo completar el análisis.', completed: 'Análisis automático guardado. Las categorías son propuestas sin validación humana.'};
            el('researchAnalysisStatus').textContent = data.message || data.failure?.message || states[data.status] || 'Estado de análisis desconocido.';
            buttons();
            if (data.status !== 'completed' || !data.result) return;
            renderAnalysis(data);
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
            el('researchForm').hidden = true; el('researchNewStudy').textContent = 'Nueva investigación';
            const select = el('researchSelect');
            if (![...select.options].some(option => option.value === study.study_id)) {
                const option = make('option', `${study.topic} · ${study.study_id.slice(0, 8)}`); option.value = study.study_id; select.append(option);
            }
            select.value = study.study_id;
            el('researchHeading').textContent = study.topic;
            el('researchSourceLabel').textContent = `${study.source_label} · ${study.synthetic === true ? 'Datos de prueba — No reales' : 'Registros recopilados'}`;
            el('researchAnalysisIntro').textContent = `${study.topic} · consultando comentarios preparados. El análisis envía sus textos a OpenAI y puede generar un costo. No realiza nuevas búsquedas.`;
            el('researchDescriptionText').textContent = study.description;
            el('researchState').textContent = labels[study.status] || study.status;
            el('researchProgress').value = study.counters.prepared; el('researchProgress').max = study.target_records;
            el('researchProgressText').textContent = `${study.counters.prepared} / ${study.target_records} preparados (${study.progress_percent} % del objetivo)`;
            const c = study.counters;
            el('researchFacts').replaceChildren(metric('Publicaciones descubiertas', c.publications_discovered, 'publication'),
                metric('Publicaciones procesadas', c.publications_processed, 'publication'),
                metric('Comentarios recibidos', c.received, 'comment'), metric('Comentarios preparados', c.prepared, 'comment'),
                metric('Excluidos', c.excluded, 'chart'), metric('Duplicados', c.duplicates, 'chart'));
            el('researchCoverage').textContent = c.received ? `${Math.round(c.prepared / c.received * 100)} % preparados de los recibidos` : 'Sin comentarios recibidos';
            el('researchBenfordStatus').textContent = c.publications_processed < 110
                ? `Análisis de Benford no aplicable: hay ${c.publications_processed} publicaciones procesadas. Una serie tan pequeña no permite frecuencias esperadas suficientes para los nueve primeros dígitos.`
                : 'Análisis de Benford no aplicable: no se ha validado una serie cuantitativa apropiada para esta investigación. El módulo existente analiza perfiles V1 por username.';
            el('researchActivity').textContent = `Última actividad: ${study.updated_at} · Motivo: ${study.stop_reason || '—'} · Último error: ${study.source === 'tiktok' ? researchErrorMessage(study.last_error) : study.last_error || '—'}`;
            el('researchWarnings').replaceChildren(...study.warnings.map(warning => make('p', warning)));
            this.message(`${labels[study.status]} · ${study.source_label}. ${study.source === 'tiktok' && study.last_error ? researchErrorMessage(study.last_error) + ' ' : ''}El progreso corresponde al objetivo, no a una plataforma externa.`);
            buttons();
        },
        records(data) {
            recordsPage = data;
            recordLabels(data.records);
            el('researchRecordsCount').textContent = `${data.total} registros preparados · ${data.records.length ? data.offset + 1 : 0}–${data.offset + data.records.length}`;
            el('researchExploreRecords').disabled = !data.total;
            if (modalMode === 'records' && el('researchEvidenceDialog').open) {
                modalEntries = data.records; renderModal();
            }
        },
    };
    const workspace = new ResearchWorkspace(researchRequest, view);
    document.querySelectorAll('#research [data-research-tab]').forEach(button => {
        button.addEventListener('click', () => tab(button.dataset.researchTab));
        button.addEventListener('keydown', event => {
            if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
            event.preventDefault(); const tabs = [...document.querySelectorAll('#research [data-research-tab]')];
            const index = tabs.indexOf(button), next = tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
            tab(next.dataset.researchTab); next.focus();
        });
    });
    el('researchExploreRecords').addEventListener('click', event => {
        if (recordsPage) showModal('Comentarios preparados', recordsPage.records, 'records', event.currentTarget);
    });
    el('researchNewStudy').addEventListener('click', () => {
        const form = el('researchForm'); form.hidden = !form.hidden;
        el('researchNewStudy').textContent = form.hidden ? 'Nueva investigación' : 'Ocultar formulario';
        if (!form.hidden) el('researchTopic').focus();
    });
    el('researchDialogSearch').addEventListener('input', renderModal);
    el('researchDialogClose').addEventListener('click', () => el('researchEvidenceDialog').close());
    el('researchEvidenceDialog').addEventListener('click', event => { if (event.target === el('researchEvidenceDialog')) el('researchEvidenceDialog').close(); });
    el('researchEvidenceDialog').addEventListener('close', () => { if (modalTrigger?.isConnected) modalTrigger.focus(); });
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

const PdfActivityHooks = (() => {
    const bridge = PdfEditor.bridge;
    const TITLES = { translate: 'pe_act_translate', search: 'pe_act_search', ai: 'pe_act_ai', fonts: 'pe_act_fonts' };
    const FAILURES = { translate: 'err_ai_failed', search: 'err_pdf_edit', ai: 'err_ai_failed' };
    const COUNTED = ['translate', 'search', 'fonts'];
    const STAGES = ['layout', 'glossary', 'translate', 'ops'];
    const FINAL = ['done', 'failed', 'cancelled'];
    const FONT_POLL_MS = 1000;
    const entries = new Map();
    let opened = false;
    let fonts = null;

    bridge.translations({
        en: {
            pe_act_translate: 'Translating document',
            pe_act_translate_count: 'Translating document… {done}/{total}',
            pe_act_search: 'Searching document',
            pe_act_search_count: 'Searching document… {done}/{total}',
            pe_act_ai: 'AI rewrite',
            pe_act_fonts: 'Preparing system fonts…',
            pe_act_fonts_count: 'Preparing system fonts… {done}/{total}',
            pe_act_stage_layout: 'Reading the page',
            pe_act_stage_glossary: 'Collecting key terms',
            pe_act_stage_translate: 'Translating',
            pe_act_stage_ops: 'Placing the text'
        },
        pl: {
            pe_act_translate: 'Tłumaczenie dokumentu',
            pe_act_translate_count: 'Tłumaczenie dokumentu… {done}/{total}',
            pe_act_search: 'Wyszukiwanie w dokumencie',
            pe_act_search_count: 'Wyszukiwanie w dokumencie… {done}/{total}',
            pe_act_ai: 'Przeredagowanie AI',
            pe_act_fonts: 'Przygotowuję czcionki systemowe…',
            pe_act_fonts_count: 'Przygotowuję czcionki systemowe… {done}/{total}',
            pe_act_stage_layout: 'Odczyt strony',
            pe_act_stage_glossary: 'Zbieranie kluczowych terminów',
            pe_act_stage_translate: 'Tłumaczenie',
            pe_act_stage_ops: 'Wstawianie tekstu'
        },
        de: {
            pe_act_translate: 'Dokument wird übersetzt',
            pe_act_translate_count: 'Dokument wird übersetzt… {done}/{total}',
            pe_act_search: 'Dokument wird durchsucht',
            pe_act_search_count: 'Dokument wird durchsucht… {done}/{total}',
            pe_act_ai: 'KI-Umformulierung',
            pe_act_fonts: 'Systemschriften werden vorbereitet…',
            pe_act_fonts_count: 'Systemschriften werden vorbereitet… {done}/{total}',
            pe_act_stage_layout: 'Seite wird gelesen',
            pe_act_stage_glossary: 'Schlüsselbegriffe werden gesammelt',
            pe_act_stage_translate: 'Übersetzung',
            pe_act_stage_ops: 'Text wird eingesetzt'
        }
    });

    function title(kind, detail = {}) {
        const key = TITLES[kind];
        return detail.total && COUNTED.includes(kind) ? bridge.t(`${key}_count`, { done: detail.done || 0, total: detail.total }) : bridge.t(key);
    }

    function stageLabel(stage) {
        return STAGES.includes(stage) ? bridge.t(`pe_act_stage_${stage}`) : null;
    }

    function eta(entry, done, total) {
        if (!done) return null;
        const perPage = (Date.now() - entry.started) / 1000 / done;
        return Math.round(perPage * (total - done) * 10) / 10;
    }

    function coreFields(entry, event) {
        if (!event.total) return {};
        const detail = { ...entry.handle.task.detail, done: event.done, total: event.total };
        if (entry.kind === 'translate') detail.eta_s = eta(entry, event.done, event.total);
        return { progress: event.done / event.total, detail, title: title(entry.kind, detail) };
    }

    function postCancel(taskId) {
        return bridge.postJson(`/api/pdf/edit/tasks/${encodeURIComponent(taskId)}/cancel`, {}).catch(() => null);
    }

    function cancel(entry) {
        entry.stopping = true;
        if (entry.cancellable) bridge.cancelTask(entry.coreId);
        if (entry.kind === 'search' && entry.server) postCancel(entry.server);
    }

    function start(event) {
        const entry = { kind: event.kind, coreId: event.id, started: Date.now(), cancellable: !!event.cancellable, server: null, stopping: false };
        const options = { titleKey: TITLES[event.kind], title: title(event.kind), total: event.total ?? null };
        if (entry.cancellable || entry.kind === 'search') options.cancel = () => cancel(entry);
        entry.handle = PdfProgress.local(event.kind, options);
        entries.set(event.id, entry);
        return entry;
    }

    function finish(entry, status) {
        entries.delete(entry.coreId);
        if (status === 'done') return entry.handle.done();
        if (status === 'cancelled' || entry.stopping) return entry.handle.update({ status: 'cancelled' });
        entry.handle.fail(FAILURES[entry.kind]);
    }

    function onCore(event) {
        if (!opened || !TITLES[event.kind]) return;
        const entry = entries.get(event.id) || (event.status === 'running' ? start(event) : null);
        if (!entry) return;
        if (event.status !== 'running') return finish(entry, event.status);
        if (entry.handle.cancelled() && !entry.stopping) cancel(entry);
        entry.handle.update(coreFields(entry, event));
    }

    function linked(task) {
        return [...entries.values()].find(entry => entry.kind === task.kind && (entry.server === task.id
            || (!FINAL.includes(task.status) && task.created_at * 1000 >= entry.started - 5000)));
    }

    function onServer(task) {
        if (!opened || !String(task.id).startsWith('tsk_')) return;
        const entry = linked(task);
        if (!entry) return;
        entry.server = task.id;
        const fields = { server_id: task.id, stage: task.stage || null, stageLabel: stageLabel(task.stage) };
        if (entry.kind === 'search' && task.detail?.total) {
            Object.assign(fields, { progress: task.progress, detail: { ...task.detail }, title: title('search', task.detail) });
        }
        if (entry.kind === 'translate' && !FINAL.includes(task.status) && typeof task.progress === 'number') {
            const { detail, progress } = entry.handle.task;
            const current = bridge.session()?.order[detail.done || 0];
            if (detail.total && task.page === current) fields.progress = Math.max(progress || 0, Math.min(1, ((detail.done || 0) + task.progress) / detail.total));
        }
        entry.handle.update(fields);
    }

    async function checkFonts() {
        const state = fonts;
        if (!state) return;
        state.timer = 0;
        const res = await fetch('/api/pdf/edit/fonts/status').then(r => r.json()).catch(() => null);
        if (fonts !== state) return;
        const status = res?.data;
        if (!status) return;
        if (status.ready) {
            state.handle?.done();
            state.handle = null;
            return;
        }
        const detail = { done: status.done, total: status.total };
        const fields = { progress: status.total ? status.done / status.total : null, detail, title: title('fonts', detail) };
        if (state.handle) state.handle.update(fields);
        else state.handle = PdfProgress.local('fonts', { titleKey: TITLES.fonts, total: status.total || null, ...fields });
        state.timer = setTimeout(checkFonts, FONT_POLL_MS);
    }

    function refreshTitles() {
        const handles = [...entries.values()].map(entry => entry.handle);
        if (fonts?.handle) handles.push(fonts.handle);
        handles.forEach(handle => handle.update({ title: title(handle.task.kind, handle.task.detail), stageLabel: stageLabel(handle.task.stage) }));
    }

    bridge.on('open', () => {
        opened = true;
        fonts = { handle: null, timer: 0 };
        checkFonts();
    });
    bridge.on('close', () => {
        opened = false;
        entries.clear();
        if (fonts) clearTimeout(fonts.timer);
        fonts = null;
    });
    bridge.on('task', onCore);
    PdfProgress.onTask('*', onServer);
    document.addEventListener('languagechange', () => opened && refreshTitles());

    return { active: () => [...entries.values()].map(entry => ({ ...entry.handle.task })) };
})();

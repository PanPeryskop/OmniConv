const PdfProgress = (() => {
    const FINAL = ['done', 'failed', 'cancelled'];
    const QUIET_KINDS = ['fonts', 'search', 'translate', 'ai'];
    const KEEP_FINISHED_MS = 60000;
    const TOAST_MS = 5000;
    const TOAST_MIN_S = 2;
    const ACTIVITY_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg>';
    const CLOSE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 6L6 18M6 6l12 12"/></svg>';
    const DONE_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>';
    const FAIL_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5M12 16.5h.01"/><circle cx="12" cy="12" r="9"/></svg>';
    const RING = '<svg viewBox="0 0 36 36" aria-hidden="true"><circle class="pe-ring-track" cx="18" cy="18" r="15"/><circle class="pe-ring-arc" cx="18" cy="18" r="15" pathLength="100"/></svg>';

    const bridge = PdfEditor.bridge;
    const handlers = {};
    const tasks = new Map();
    const locals = new Map();
    const finishedAt = new Map();
    const pending = new Set();
    let timer = 0;
    let fileId = null;
    let socket = null;
    let live = false;
    let ui = null;
    let frame = 0;
    let toastTimer = 0;

    bridge.translations({
        en: {
            pe_activity_empty: 'Nothing running right now',
            pe_activity_count_one: '{count} task running',
            pe_activity_count_other: '{count} tasks running',
            pe_task_ocr: 'Text recognition (OCR)',
            pe_task_translate: 'Translation',
            pe_task_search: 'Search',
            pe_task_save: 'Saving',
            pe_task_sign: 'Signing',
            pe_task_ai: 'AI rewrite',
            pe_task_agent: 'AI assistant',
            pe_task_fonts: 'Preparing fonts',
            pe_task_other: 'Task',
            pe_stage_render: 'Rendering the page',
            pe_stage_orientation: 'Detecting orientation',
            pe_stage_detect: 'Finding text lines',
            pe_stage_recognize: 'Recognizing text',
            pe_stage_layout: 'Building the text layer',
            pe_stage_fonts: 'Matching fonts',
            pe_task_page: 'Page {page}',
            pe_task_queued: 'Waiting',
            pe_task_running: 'In progress',
            pe_task_done: 'Done',
            pe_task_failed: 'Failed',
            pe_task_cancelled: 'Cancelled',
            pe_task_cancel: 'Cancel',
            pe_task_steps: '{done} of {total}',
            pe_task_eta: 'about {time} left',
            pe_task_eta_s: '{n} s',
            pe_task_eta_min: '{n} min',
            pe_task_done_toast: '{title} finished',
            pe_task_failed_toast: '{title} failed',
            pe_task_show: 'Show'
        },
        pl: {
            pe_activity_empty: 'Nic się teraz nie dzieje',
            pe_activity_count_one: '{count} zadanie w toku',
            pe_activity_count_few: '{count} zadania w toku',
            pe_activity_count_many: '{count} zadań w toku',
            pe_activity_count_other: '{count} zadania w toku',
            pe_task_ocr: 'Rozpoznawanie tekstu (OCR)',
            pe_task_translate: 'Tłumaczenie',
            pe_task_search: 'Wyszukiwanie',
            pe_task_save: 'Zapisywanie',
            pe_task_sign: 'Podpisywanie',
            pe_task_ai: 'Przeredagowanie AI',
            pe_task_agent: 'Asystent AI',
            pe_task_fonts: 'Przygotowanie czcionek',
            pe_task_other: 'Zadanie',
            pe_stage_render: 'Renderowanie strony',
            pe_stage_orientation: 'Wykrywanie orientacji',
            pe_stage_detect: 'Wykrywanie linii tekstu',
            pe_stage_recognize: 'Rozpoznawanie tekstu',
            pe_stage_layout: 'Budowanie warstwy tekstu',
            pe_stage_fonts: 'Dobieranie kroju',
            pe_task_page: 'Strona {page}',
            pe_task_queued: 'W kolejce',
            pe_task_running: 'W toku',
            pe_task_done: 'Gotowe',
            pe_task_failed: 'Nie powiodło się',
            pe_task_cancelled: 'Anulowano',
            pe_task_cancel: 'Anuluj',
            pe_task_steps: '{done} z {total}',
            pe_task_eta: 'jeszcze ok. {time}',
            pe_task_eta_s: '{n} s',
            pe_task_eta_min: '{n} min',
            pe_task_done_toast: '{title}: gotowe',
            pe_task_failed_toast: '{title}: błąd',
            pe_task_show: 'Pokaż'
        },
        de: {
            pe_activity_empty: 'Gerade läuft nichts',
            pe_activity_count_one: '{count} Aufgabe läuft',
            pe_activity_count_other: '{count} Aufgaben laufen',
            pe_task_ocr: 'Texterkennung (OCR)',
            pe_task_translate: 'Übersetzung',
            pe_task_search: 'Suche',
            pe_task_save: 'Speichern',
            pe_task_sign: 'Signieren',
            pe_task_ai: 'KI-Umformulierung',
            pe_task_agent: 'KI-Assistent',
            pe_task_fonts: 'Schriften vorbereiten',
            pe_task_other: 'Aufgabe',
            pe_stage_render: 'Seite wird gerendert',
            pe_stage_orientation: 'Ausrichtung wird erkannt',
            pe_stage_detect: 'Textzeilen werden gesucht',
            pe_stage_recognize: 'Text wird erkannt',
            pe_stage_layout: 'Textebene wird erstellt',
            pe_stage_fonts: 'Schriften werden zugeordnet',
            pe_task_page: 'Seite {page}',
            pe_task_queued: 'Wartet',
            pe_task_running: 'Läuft',
            pe_task_done: 'Fertig',
            pe_task_failed: 'Fehlgeschlagen',
            pe_task_cancelled: 'Abgebrochen',
            pe_task_cancel: 'Abbrechen',
            pe_task_steps: '{done} von {total}',
            pe_task_eta: 'noch ca. {time}',
            pe_task_eta_s: '{n} s',
            pe_task_eta_min: '{n} Min.',
            pe_task_done_toast: '{title} abgeschlossen',
            pe_task_failed_toast: '{title} fehlgeschlagen',
            pe_task_show: 'Anzeigen'
        }
    });

    const now = () => Date.now() / 1000;
    const isFinal = task => FINAL.includes(task.status);
    const isLocal = task => String(task.id).startsWith('local_');
    const known = key => typeof translations !== 'undefined' && key in translations.en;

    function emit(task) {
        [...(handlers[task.kind] || []), ...(handlers['*'] || [])].forEach(fn => {
            try {
                fn(task);
            } catch (err) {
                console.error(err);
            }
        });
    }

    function remember(task) {
        if (task.file_id ? task.file_id !== fileId : !fileId && !isLocal(task)) return;
        const previous = tasks.get(task.id);
        if (previous && (isFinal(previous) || task.updated_at < previous.updated_at)) return;
        if (previous && previous.updated_at === task.updated_at && previous.status === task.status) return;
        tasks.set(task.id, task);
        if (isFinal(task)) finishedAt.set(task.id, Date.now());
        emit(task);
        if (previous && isFinal(task)) announce(task);
        scheduleRender();
    }

    async function fetchTasks() {
        const id = fileId;
        const res = await fetch(`/api/pdf/edit/tasks?file_id=${encodeURIComponent(id)}`).then(r => r.json()).catch(() => null);
        if (id === fileId) (res?.data?.tasks || []).forEach(remember);
    }

    async function poll() {
        clearTimeout(timer);
        timer = 0;
        if (!fileId || live) return;
        await fetchTasks();
        if (!fileId || live || timer) return;
        const active = [...tasks.values()].some(task => !isFinal(task));
        timer = setTimeout(poll, active ? 1000 : 3000);
    }

    function join() {
        socket.emit('editor_join', {}, reply => {
            live = !!reply?.joined;
            if (!live) return poll();
            clearTimeout(timer);
            timer = 0;
            if (fileId) fetchTasks();
        });
    }

    function connect() {
        if (socket) return;
        socket = (typeof appState !== 'undefined' && appState.socket) || (typeof io !== 'undefined' ? io() : null);
        if (!socket) return;
        socket.on('connect', join);
        socket.on('disconnect', () => {
            live = false;
            poll();
        });
        socket.on('editor_task', remember);
        if (socket.connected) join();
    }

    function start(id) {
        fileId = id;
        buildUi();
        connect();
        poll();
        if (live) fetchTasks();
    }

    function stop() {
        fileId = null;
        clearTimeout(timer);
        timer = 0;
        tasks.clear();
        locals.clear();
        finishedAt.clear();
        pending.clear();
        openCenter(false);
        hideToast();
        scheduleRender();
    }

    function onTask(kind, fn) {
        (handlers[kind] ||= []).push(fn);
    }

    function track(taskId) {
        if (!live && !timer && fileId) poll();
        else if (live && fileId && !tasks.has(taskId)) fetchTasks();
        return taskId;
    }

    function get(taskId) {
        return tasks.get(taskId) || null;
    }

    function local(kind, options = {}) {
        const { total, ...rest } = options;
        const stamp = now();
        const task = { id: `local_${Math.random().toString(36).slice(2)}`, kind, status: 'running', stage: null, progress: null, detail: total ? { done: 0, total } : {}, page: null, created_at: stamp, updated_at: stamp, ...rest };
        const touch = fields => {
            if (isFinal(task)) return;
            Object.assign(task, fields, { updated_at: Math.max(now(), task.updated_at + 0.001) });
            remember({ ...task, detail: { ...task.detail } });
        };
        locals.set(task.id, { task, touch });
        touch({});
        return {
            task,
            update: fields => touch(fields),
            done: () => touch({ status: 'done', progress: 1 }),
            fail: code => touch({ status: 'failed', error: { code } }),
            cancelled: () => task.status === 'cancelled'
        };
    }

    async function cancel(taskId) {
        const task = tasks.get(taskId);
        if (!task || isFinal(task) || pending.has(taskId)) return;
        const entry = locals.get(taskId);
        if (entry) {
            if (typeof entry.task.cancel === 'function') entry.task.cancel();
            entry.touch({ status: 'cancelled' });
            return;
        }
        pending.add(taskId);
        scheduleRender();
        const { body } = await bridge.postJson(`/api/pdf/edit/tasks/${encodeURIComponent(taskId)}/cancel`, {}).catch(() => ({ body: {} }));
        pending.delete(taskId);
        const current = tasks.get(taskId);
        if (body?.data?.cancelled && current && !isFinal(current)) remember({ ...current, status: 'cancelled', updated_at: current.updated_at + 0.001 });
        scheduleRender();
    }

    function cancellable(task) {
        if (isFinal(task)) return false;
        return isLocal(task) ? typeof locals.get(task.id)?.task.cancel === 'function' : true;
    }

    function fraction(task) {
        if (task.status === 'done') return 1;
        if (typeof task.progress === 'number') return Math.min(1, Math.max(0, task.progress));
        const { done, total } = task.detail || {};
        return total ? Math.min(1, done / total) : null;
    }

    function kindTitle(task) {
        const key = `pe_task_${task.kind}`;
        return bridge.t(known(key) ? key : 'pe_task_other');
    }

    function title(task) {
        return task.title || (task.titleKey ? bridge.t(task.titleKey) : kindTitle(task));
    }

    function pageNumber(page) {
        const order = bridge.session()?.order || [];
        const position = order.indexOf(page);
        return position >= 0 ? position + 1 : page + 1;
    }

    function stageText(task) {
        if (isFinal(task)) return bridge.t(`pe_task_${task.status}`);
        const key = `pe_stage_${task.stage}`;
        if (task.stageLabel) return task.stageLabel;
        if (task.stage && known(key)) return bridge.t(key);
        return bridge.t(task.status === 'queued' ? 'pe_task_queued' : 'pe_task_running');
    }

    function etaText(seconds) {
        const time = seconds < 60 ? bridge.t('pe_task_eta_s', { n: Math.max(1, Math.ceil(seconds)) }) : bridge.t('pe_task_eta_min', { n: Math.round(seconds / 60) });
        return bridge.t('pe_task_eta', { time });
    }

    function infoText(task) {
        if (isFinal(task)) return task.status === 'failed' ? task.error?.message || '' : '';
        const { done, total, eta_s: eta } = task.detail || {};
        const value = fraction(task);
        const parts = [];
        if (total) parts.push(bridge.t('pe_task_steps', { done: done || 0, total }));
        else if (value !== null) parts.push(`${Math.round(value * 100)}%`);
        if (typeof eta === 'number' && eta > 0) parts.push(etaText(eta));
        return parts.join(' · ');
    }

    function element(tag, className, html = '') {
        const el = document.createElement(tag);
        el.className = className;
        el.innerHTML = html;
        return el;
    }

    function buildUi() {
        if (ui) return;
        const root = document.getElementById('pdfEditor');
        const button = bridge.button('activity');
        if (!root || !button) return;
        const strip = element('div', 'pe-progress-strip hidden', '<div class="pe-progress-strip-fill"></div>');
        strip.setAttribute('role', 'progressbar');
        strip.setAttribute('aria-valuemin', '0');
        strip.setAttribute('aria-valuemax', '100');
        const panel = element('div', 'pe-activity hidden', `<div class="pe-activity-grabber" aria-hidden="true"></div>
            <div class="pe-activity-head"><span class="pe-activity-title"></span><button type="button" class="pe-icon-btn" data-activity="close">${CLOSE_ICON}</button></div>
            <div class="pe-activity-list" role="list"></div>
            <p class="pe-activity-empty"></p>`);
        panel.id = 'peActivity';
        panel.tabIndex = -1;
        panel.setAttribute('role', 'dialog');
        const backdrop = element('div', 'pe-activity-backdrop hidden');
        const toast = element('div', 'pe-task-toast hidden');
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        root.querySelector('.pe-top').after(strip);
        root.append(backdrop, panel, toast);
        ui = { root, button, badge: button.querySelector('.pe-badge'), strip, panel, backdrop, toast, list: panel.querySelector('.pe-activity-list'), items: new Map(), thumbs: document.getElementById('peThumbs') };
        button.hidden = false;
        button.setAttribute('aria-controls', panel.id);
        button.setAttribute('aria-haspopup', 'dialog');
        button.setAttribute('aria-expanded', 'false');
        button.addEventListener('click', () => openCenter(panel.classList.contains('hidden')));
        panel.addEventListener('click', onPanelClick);
        backdrop.addEventListener('click', () => openCenter(false));
        toast.addEventListener('click', onToastClick);
        document.addEventListener('pointerdown', onOutside, true);
        document.addEventListener('keydown', onKey, true);
        document.addEventListener('languagechange', () => render());
        window.addEventListener('resize', place);
        if (ui.thumbs) new MutationObserver(renderRings).observe(ui.thumbs, { childList: true });
    }

    function place() {
        if (!ui) return;
        const top = `${Math.round(ui.root.querySelector('.pe-top').getBoundingClientRect().bottom + 8)}px`;
        ui.panel.style.setProperty('--pe-activity-top', top);
        ui.toast.style.setProperty('--pe-activity-top', top);
    }

    function openCenter(show) {
        if (!ui) return;
        const visible = !ui.panel.classList.contains('hidden');
        if (show === visible) return;
        place();
        ui.panel.classList.toggle('hidden', !show);
        ui.backdrop.classList.toggle('hidden', !show);
        ui.button.setAttribute('aria-expanded', String(show));
        if (show) {
            render();
            ui.panel.focus({ preventScroll: true });
        } else if (ui.panel.contains(document.activeElement)) {
            ui.button.focus({ preventScroll: true });
        }
    }

    function onOutside(e) {
        if (!ui || ui.panel.classList.contains('hidden')) return;
        if (ui.panel.contains(e.target) || ui.button.contains(e.target) || e.target === ui.backdrop) return;
        openCenter(false);
    }

    function onKey(e) {
        if (e.key !== 'Escape' || !ui || ui.panel.classList.contains('hidden')) return;
        e.stopPropagation();
        openCenter(false);
    }

    function onPanelClick(e) {
        const action = e.target.closest('[data-activity]');
        if (!action) return;
        if (action.dataset.activity === 'close') return openCenter(false);
        if (action.dataset.activity === 'cancel') cancel(action.closest('[data-task]').dataset.task);
    }

    function showPage(page) {
        if (!bridge.session()) return;
        bridge.focus(page, [], 'applied');
        bridge.clearFocus();
    }

    function onToastClick(e) {
        const action = e.target.closest('[data-toast]')?.dataset.toast;
        if (action === 'show') showPage(Number(ui.toast.dataset.page));
        if (action) hideToast();
    }

    function announce(task) {
        if (!ui || task.status === 'cancelled' || QUIET_KINDS.includes(task.kind)) return;
        const long = task.updated_at - task.created_at >= TOAST_MIN_S;
        if (task.status === 'done' && task.page == null && !long) return;
        const failed = task.status === 'failed';
        const message = bridge.t(failed ? 'pe_task_failed_toast' : 'pe_task_done_toast', { title: kindTitle(task) });
        const page = task.page == null ? '' : ` · ${bridge.t('pe_task_page', { page: pageNumber(task.page) })}`;
        const show = task.page == null ? '' : `<button type="button" class="pe-task-toast-show" data-toast="show">${bridge.escapeHtml(bridge.t('pe_task_show'))}</button>`;
        place();
        ui.toast.dataset.page = task.page ?? '';
        ui.toast.classList.toggle('failed', failed);
        ui.toast.innerHTML = `<span class="pe-task-toast-icon">${failed ? FAIL_ICON : DONE_ICON}</span>
            <span class="pe-task-toast-text">${bridge.escapeHtml(message + page)}</span>${show}
            <button type="button" class="pe-icon-btn pe-task-toast-close" data-toast="close" aria-label="${bridge.escapeHtml(bridge.t('close'))}">${CLOSE_ICON}</button>`;
        ui.toast.classList.remove('hidden');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(hideToast, TOAST_MS);
    }

    function hideToast() {
        clearTimeout(toastTimer);
        ui?.toast.classList.add('hidden');
    }

    function scheduleRender() {
        if (!frame) frame = requestAnimationFrame(render);
    }

    function prune() {
        const limit = Date.now() - KEEP_FINISHED_MS;
        finishedAt.forEach((at, id) => {
            if (at >= limit) return;
            finishedAt.delete(id);
            tasks.delete(id);
            locals.delete(id);
        });
    }

    function sorted(all = false) {
        const linked = new Set([...tasks.values()].map(task => task.server_id).filter(Boolean));
        return [...tasks.values()].filter(task => all || !linked.has(task.id)).sort((a, b) => (isFinal(a) - isFinal(b)) || (isFinal(a) ? b.updated_at - a.updated_at : b.created_at - a.created_at));
    }

    function render() {
        frame = 0;
        if (!ui) return;
        prune();
        const list = sorted();
        const active = list.filter(task => !isFinal(task));
        renderButton(active.length);
        renderStrip(active[0]);
        renderRings();
        if (!ui.panel.classList.contains('hidden')) renderPanel(list);
    }

    function renderButton(count) {
        const label = bridge.t('pe_activity');
        ui.badge.hidden = !count;
        ui.badge.textContent = count ? String(count) : '';
        ui.button.classList.toggle('busy', count > 0);
        ui.button.setAttribute('aria-label', count ? `${label}, ${bridge.t('pe_activity_count', { count })}` : label);
    }

    function setBar(fill, value) {
        fill.classList.toggle('indeterminate', value === null);
        fill.style.width = value === null ? '' : `${Math.round(value * 1000) / 10}%`;
    }

    function renderStrip(task) {
        ui.strip.classList.toggle('hidden', !task);
        if (!task) return;
        const value = fraction(task);
        setBar(ui.strip.firstElementChild, value);
        ui.strip.setAttribute('aria-label', title(task));
        if (value === null) ui.strip.removeAttribute('aria-valuenow');
        else ui.strip.setAttribute('aria-valuenow', String(Math.round(value * 100)));
    }

    function renderRings() {
        if (!ui?.thumbs) return;
        const byPage = new Map();
        sorted(true).filter(task => !isFinal(task) && task.page != null).forEach(task => byPage.has(task.page) || byPage.set(task.page, task));
        ui.thumbs.querySelectorAll('.pe-thumb').forEach(thumb => {
            const task = byPage.get(Number(thumb.dataset.id));
            let ring = thumb.querySelector('.pe-thumb-ring');
            if (!task) return ring?.remove();
            if (!ring) {
                ring = element('div', 'pe-thumb-ring', RING);
                ring.setAttribute('role', 'progressbar');
                thumb.append(ring);
            }
            const value = fraction(task);
            ring.classList.toggle('indeterminate', value === null);
            ring.querySelector('.pe-ring-arc').style.strokeDashoffset = value === null ? '' : String(100 - value * 100);
            ring.setAttribute('aria-label', `${title(task)} · ${stageText(task)}`);
            if (value === null) ring.removeAttribute('aria-valuenow');
            else ring.setAttribute('aria-valuenow', String(Math.round(value * 100)));
        });
    }

    function renderPanel(list) {
        const close = ui.panel.querySelector('[data-activity="close"]');
        ui.panel.querySelector('.pe-activity-title').textContent = bridge.t('pe_activity');
        ui.panel.setAttribute('aria-label', bridge.t('pe_activity'));
        close.setAttribute('aria-label', bridge.t('close'));
        close.title = bridge.t('close');
        ui.panel.querySelector('.pe-activity-empty').textContent = list.length ? '' : bridge.t('pe_activity_empty');
        ui.panel.classList.toggle('empty', !list.length);
        const ids = new Set(list.map(task => task.id));
        ui.items.forEach((item, id) => {
            if (ids.has(id)) return;
            item.remove();
            ui.items.delete(id);
        });
        list.forEach((task, index) => {
            const item = ui.items.get(task.id) || createItem(task.id);
            updateItem(item, task);
            if (ui.list.children[index] !== item) ui.list.insertBefore(item, ui.list.children[index] || null);
        });
    }

    function createItem(id) {
        const item = element('div', 'pe-task', `<div class="pe-task-main">
                <div class="pe-task-row"><span class="pe-task-title"></span><span class="pe-task-page"></span></div>
                <div class="pe-task-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"><div class="pe-task-fill"></div></div>
                <div class="pe-task-row pe-task-meta"><span class="pe-task-stage"></span><span class="pe-task-info"></span></div>
            </div>
            <button type="button" class="pe-task-cancel" data-activity="cancel"></button>`);
        item.dataset.task = id;
        item.setAttribute('role', 'listitem');
        ui.items.set(id, item);
        return item;
    }

    function updateItem(item, task) {
        const value = fraction(task);
        const bar = item.querySelector('.pe-task-bar');
        const cancelButton = item.querySelector('.pe-task-cancel');
        item.className = `pe-task ${task.status}`;
        item.querySelector('.pe-task-title').textContent = title(task);
        item.querySelector('.pe-task-page').textContent = task.page == null ? '' : bridge.t('pe_task_page', { page: pageNumber(task.page) });
        item.querySelector('.pe-task-stage').textContent = stageText(task);
        item.querySelector('.pe-task-info').textContent = infoText(task);
        setBar(item.querySelector('.pe-task-fill'), value === null && isFinal(task) ? 0 : value);
        bar.setAttribute('aria-label', title(task));
        if (value === null) bar.removeAttribute('aria-valuenow');
        else bar.setAttribute('aria-valuenow', String(Math.round(value * 100)));
        cancelButton.hidden = !cancellable(task);
        cancelButton.disabled = pending.has(task.id);
        cancelButton.textContent = bridge.t('pe_task_cancel');
    }

    bridge.addMenuItem({ id: 'activity', icon: ACTIVITY_ICON, labelKey: 'pe_activity', run: () => openCenter(true) });
    bridge.on('open', session => start(session.fileId));
    bridge.on('close', stop);

    return { onTask, track, get, local };
})();

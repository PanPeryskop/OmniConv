const PdfOcrView = (() => {
    const bridge = PdfEditor.bridge;
    const STORE = 'pe_ocr_page_seconds';
    const KEEP = 5;
    const FINAL = ['done', 'failed', 'cancelled'];
    const views = new Map();
    const scanned = new Set();
    const starts = new Map();
    let notice = null;
    let dismissed = false;

    bridge.translations({
        en: {
            pe_ocr_queued: 'Waiting in queue…',
            pe_ocr_render: 'Preparing the page…',
            pe_ocr_orientation: 'Checking orientation…',
            pe_ocr_detect_one: 'Found 1 line',
            pe_ocr_detect_other: 'Found {count} lines',
            pe_ocr_recognize: 'Recognized {done}/{total} lines',
            pe_ocr_layout: 'Building the text layer…',
            pe_ocr_fonts: 'Matching fonts…',
            pe_ocr_done: 'Text recognized',
            pe_ocr_eta: 'about {time}',
            pe_ocr_seconds: '{count} s',
            pe_ocr_minutes: '{count} min',
            pe_ocr_cancel: 'Cancel',
            pe_ocr_cancelled: 'Recognition cancelled',
            pe_ocr_failed: 'Recognition failed',
            pe_ocr_retry: 'Try again',
            pe_ocr_all_one: 'This document has 1 scanned page.',
            pe_ocr_all_other: 'This document has {count} scanned pages.',
            pe_ocr_all_action: 'Recognize all',
            pe_ocr_all_label: 'Recognize scanned pages'
        },
        pl: {
            pe_ocr_queued: 'Czeka w kolejce…',
            pe_ocr_render: 'Przygotowuję stronę…',
            pe_ocr_orientation: 'Sprawdzam orientację…',
            pe_ocr_detect_one: 'Znaleziono 1 linię',
            pe_ocr_detect_few: 'Znaleziono {count} linie',
            pe_ocr_detect_many: 'Znaleziono {count} linii',
            pe_ocr_detect_other: 'Znaleziono {count} linii',
            pe_ocr_recognize: 'Rozpoznano {done}/{total} linii',
            pe_ocr_layout: 'Tworzę warstwę tekstu…',
            pe_ocr_fonts: 'Dobieram krój pisma…',
            pe_ocr_done: 'Tekst rozpoznany',
            pe_ocr_eta: 'ok. {time}',
            pe_ocr_seconds: '{count} s',
            pe_ocr_minutes: '{count} min',
            pe_ocr_cancel: 'Anuluj',
            pe_ocr_cancelled: 'Rozpoznawanie anulowane',
            pe_ocr_failed: 'Rozpoznawanie nie powiodło się',
            pe_ocr_retry: 'Spróbuj ponownie',
            pe_ocr_all_one: 'Ten dokument ma 1 zeskanowaną stronę.',
            pe_ocr_all_few: 'Ten dokument ma {count} zeskanowane strony.',
            pe_ocr_all_many: 'Ten dokument ma {count} zeskanowanych stron.',
            pe_ocr_all_other: 'Ten dokument ma {count} zeskanowanych stron.',
            pe_ocr_all_action: 'Rozpoznaj wszystkie',
            pe_ocr_all_label: 'Rozpoznanie zeskanowanych stron'
        },
        de: {
            pe_ocr_queued: 'Wartet in der Warteschlange…',
            pe_ocr_render: 'Seite wird vorbereitet…',
            pe_ocr_orientation: 'Ausrichtung wird geprüft…',
            pe_ocr_detect_one: '1 Zeile gefunden',
            pe_ocr_detect_other: '{count} Zeilen gefunden',
            pe_ocr_recognize: '{done}/{total} Zeilen erkannt',
            pe_ocr_layout: 'Textebene wird erstellt…',
            pe_ocr_fonts: 'Schriftart wird zugeordnet…',
            pe_ocr_done: 'Text erkannt',
            pe_ocr_eta: 'ca. {time}',
            pe_ocr_seconds: '{count} s',
            pe_ocr_minutes: '{count} min',
            pe_ocr_cancel: 'Abbrechen',
            pe_ocr_cancelled: 'Erkennung abgebrochen',
            pe_ocr_failed: 'Erkennung fehlgeschlagen',
            pe_ocr_retry: 'Erneut versuchen',
            pe_ocr_all_one: 'Dieses Dokument hat 1 gescannte Seite.',
            pe_ocr_all_other: 'Dieses Dokument hat {count} gescannte Seiten.',
            pe_ocr_all_action: 'Alle erkennen',
            pe_ocr_all_label: 'Gescannte Seiten erkennen'
        }
    });

    function history() {
        try {
            const list = JSON.parse(localStorage.getItem(STORE) || '[]');
            return Array.isArray(list) ? list.filter(Number.isFinite) : [];
        } catch (err) {
            return [];
        }
    }

    function remember(seconds) {
        if (!(seconds > 0)) return;
        try {
            localStorage.setItem(STORE, JSON.stringify([...history(), Math.round(seconds * 10) / 10].slice(-KEEP)));
        } catch (err) {
            return;
        }
    }

    function average() {
        const list = history();
        return list.length ? list.reduce((a, b) => a + b, 0) / list.length : null;
    }

    function estimate(view) {
        const task = view.task;
        const since = Date.now() / 1000 - view.received;
        if (Number.isFinite(task.detail?.eta_s)) return Math.max(1, task.detail.eta_s - since);
        const mean = average();
        const begin = starts.get(task.id);
        if (mean === null || typeof begin !== 'number') return null;
        return Math.max(1, mean - (task.updated_at - begin) - since);
    }

    function duration(seconds) {
        const t = bridge.t;
        if (seconds < 60) return t('pe_ocr_seconds', { count: Math.max(5, Math.ceil(seconds / 5) * 5) });
        return t('pe_ocr_minutes', { count: Math.round(seconds / 60) });
    }

    function pageElement(pageId) {
        return document.querySelector(`#pdfEditor .pe-page[data-page="${pageId}"]`);
    }

    function pct(box, size) {
        const [w, h] = size;
        const [x0, y0, x1, y1] = box;
        return `left:${(x0 / w) * 100}%;top:${(y0 / h) * 100}%;width:${((x1 - x0) / w) * 100}%;height:${((y1 - y0) / h) * 100}%`;
    }

    function stageText(view) {
        const t = bridge.t;
        const { status, stage, detail = {} } = view.task;
        const boxes = detail.boxes || [];
        if (status === 'cancelled') return t('pe_ocr_cancelled');
        if (status === 'failed') return t('pe_ocr_failed');
        if (status === 'done') return t('pe_ocr_done');
        if (status === 'queued') return t('pe_ocr_queued');
        if (stage === 'recognize') return t('pe_ocr_recognize', { done: Math.min(detail.lines || 0, boxes.length), total: boxes.length });
        if (stage === 'detect') return t('pe_ocr_detect', { count: boxes.length });
        return t(`pe_ocr_${stage || 'render'}`);
    }

    function labelText(view) {
        const text = stageText(view);
        if (FINAL.includes(view.task.status) || ['layout', 'fonts'].includes(view.task.stage)) return text;
        const eta = estimate(view);
        return eta === null ? text : `${text} · ${bridge.t('pe_ocr_eta', { time: duration(eta) })}`;
    }

    function build(view) {
        const t = bridge.t;
        const el = document.createElement('div');
        el.className = 'pe-ocr';
        el.dataset.task = view.task.id;
        el.innerHTML = `<div class="pe-ocr-boxes"></div><div class="pe-ocr-scan"></div>
            <div class="pe-ocr-bar" role="status" aria-live="polite">
                <span class="pe-ocr-ring" aria-hidden="true"></span>
                <span class="pe-ocr-label"></span>
                <button type="button" class="pe-chip pe-ocr-action" data-ocr="cancel">${bridge.escapeHtml(t('pe_ocr_cancel'))}</button>
                <button type="button" class="pe-icon-btn pe-ocr-close" data-ocr="close" aria-label="${bridge.escapeHtml(t('close'))}" title="${bridge.escapeHtml(t('close'))}">${bridge.icon('close')}</button>
            </div>`;
        el.addEventListener('click', e => {
            const action = e.target.closest('[data-ocr]')?.dataset.ocr;
            if (action === 'cancel') cancel(view);
            else if (action === 'retry') retry(view);
            else if (action === 'close') remove(view.task.page);
        });
        return el;
    }

    function attach(view) {
        const host = pageElement(view.task.page);
        if (!host) return false;
        if (!view.el) view.el = build(view);
        if (view.el.parentNode !== host) host.appendChild(view.el);
        return true;
    }

    function drawBoxes(view) {
        const { boxes, size, lines = 0 } = view.task.detail || {};
        const layer = view.el.querySelector('.pe-ocr-boxes');
        if (!boxes || !size) return;
        if (view.drawn !== boxes.length || view.size !== size.join()) {
            layer.innerHTML = boxes.map(box => `<i style="${pct(box, size)}"></i>`).join('');
            view.drawn = boxes.length;
            view.size = size.join();
        }
        const filled = view.task.status === 'done' || ['layout', 'fonts'].includes(view.task.stage) ? boxes.length : Math.min(lines, boxes.length);
        [...layer.children].forEach((box, i) => box.classList.toggle('done', i < filled));
    }

    function paint(view) {
        if (!attach(view)) return;
        const { status, progress } = view.task;
        const ended = ['cancelled', 'failed'].includes(status);
        view.el.dataset.status = status;
        view.el.dataset.stage = view.task.stage || '';
        view.el.style.setProperty('--pe-ocr-progress', `${Math.round((progress || 0) * 100)}%`);
        view.el.querySelector('.pe-ocr-label').textContent = labelText(view);
        const action = view.el.querySelector('.pe-ocr-action');
        action.dataset.ocr = ended ? 'retry' : 'cancel';
        action.textContent = bridge.t(ended ? 'pe_ocr_retry' : 'pe_ocr_cancel');
        action.hidden = status === 'done';
        view.el.querySelector('.pe-ocr-close').hidden = !ended;
        drawBoxes(view);
    }

    function remove(pageId) {
        const view = views.get(pageId);
        if (!view) return;
        view.el?.remove();
        views.delete(pageId);
    }

    async function cancel(view) {
        const id = view.task.id;
        view.task = { ...view.task, status: 'cancelled' };
        view.received = Date.now() / 1000;
        paint(view);
        await bridge.postJson(`/api/pdf/edit/tasks/${encodeURIComponent(id)}/cancel`, {});
    }

    function retry(view) {
        const page = view.task.page;
        remove(page);
        bridge.apply([{ type: 'ocr', page, retry: Date.now() }], { label: bridge.t('pe_ocr_retry') });
    }

    function offscreen(pageId) {
        const el = pageElement(pageId);
        if (!el) return true;
        const rect = el.getBoundingClientRect();
        return rect.bottom < 0 || rect.top > window.innerHeight;
    }

    function measure(task) {
        const begin = starts.get(task.id);
        if (begin === undefined && !FINAL.includes(task.status) && task.status !== 'queued' && task.stage && task.stage !== 'render') starts.set(task.id, task.updated_at);
        if (task.status === 'done' && typeof begin === 'number') {
            remember(task.updated_at - begin);
            starts.set(task.id, true);
        }
    }

    function onTask(task) {
        if (task.page === null || task.page === undefined) return;
        measure(task);
        let view = views.get(task.page);
        if (!view || view.task.id !== task.id) {
            if (FINAL.includes(task.status)) return;
            if (view) remove(task.page);
            view = { task, el: null, received: Date.now() / 1000, drawn: -1, size: '', kicked: false };
            views.set(task.page, view);
        }
        view.task = task;
        view.received = Date.now() / 1000;
        if (task.stage === 'layout' && !view.kicked && offscreen(task.page)) {
            view.kicked = true;
            bridge.layout(task.page);
        }
        paint(view);
    }

    function tick() {
        views.forEach(view => {
            if (!FINAL.includes(view.task.status)) paint(view);
        });
    }

    function candidates() {
        return [...scanned].filter(pageId => !bridge.opsForPage(pageId).some(op => op.type === 'ocr')).sort((a, b) => a - b);
    }

    function ensureNotice() {
        if (notice?.isConnected) return notice;
        const dock = document.querySelector('#pdfEditor .pe-dock');
        if (!dock) return null;
        notice = document.createElement('div');
        notice.className = 'pe-ocr-notice';
        notice.setAttribute('role', 'status');
        notice.hidden = true;
        notice.addEventListener('click', e => {
            const action = e.target.closest('[data-ocr-all]')?.dataset.ocrAll;
            if (action === 'run') recognizeAll();
            else if (action === 'dismiss') {
                dismissed = true;
                renderNotice();
            }
        });
        dock.insertBefore(notice, dock.querySelector('#peNotice'));
        return notice;
    }

    function renderNotice() {
        const el = ensureNotice();
        if (!el) return;
        const pages = candidates();
        const show = !dismissed && pages.length >= 2;
        el.hidden = !show;
        if (!show) return;
        const { t, escapeHtml, icon } = bridge;
        el.innerHTML = `${icon('text')}<span>${escapeHtml(t('pe_ocr_all', { count: pages.length }))}</span>
            <button type="button" class="pe-chip active" data-ocr-all="run">${escapeHtml(t('pe_ocr_all_action'))}</button>
            <button type="button" class="pe-icon-btn" data-ocr-all="dismiss" aria-label="${escapeHtml(t('close'))}" title="${escapeHtml(t('close'))}">${icon('close')}</button>`;
    }

    async function recognizeAll() {
        const pages = candidates();
        if (!pages.length) return;
        bridge.apply(pages.map(page => ({ type: 'ocr', page })), { label: bridge.t('pe_ocr_all_label') });
        renderNotice();
        for (const page of pages) {
            await bridge.layout(page).catch(() => null);
        }
    }

    function onPreview({ pageId, layout }) {
        if (layout?.scanned) scanned.add(pageId);
        else scanned.delete(pageId);
        const view = views.get(pageId);
        if (view && !['cancelled', 'failed'].includes(view.task.status)) remove(pageId);
        else if (view) paint(view);
        renderNotice();
    }

    function reset() {
        [...views.keys()].forEach(remove);
        scanned.clear();
        dismissed = false;
        if (notice) notice.hidden = true;
    }

    PdfProgress.onTask('ocr', onTask);
    bridge.on('preview', onPreview);
    bridge.on('ops', renderNotice);
    bridge.on('open', reset);
    bridge.on('close', reset);
    setInterval(tick, 1000);

    return { views, candidates };
})();

const PdfEditor = (() => {
    const TOOLS = ['edit', 'text', 'sign', 'image', 'markup', 'draw', 'shape', 'note', 'whiteout', 'redact'];
    const ICONS = {
        edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
        text: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
        shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M8.5 12l2.5 2.5 4.5-5"/>',
        sparkles: '<path d="M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z"/><path d="M19 15l.8 2.2 2.2.8-2.2.8L19 21l-.8-2.2-2.2-.8 2.2-.8z"/>',
        sign: '<path d="M3 17c2-1 3-6 5-6s1 5 3 5 2-3 4-3 2 2 3 2"/><path d="M3 21h18"/><path d="M15 4l5 5-6 6h-5v-5z"/>',
        date: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/>',
        cross: '<path d="M6 6l12 12M18 6L6 18"/>',
        image: '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="M21 16l-5-5-9 9"/>',
        markup: '<path d="M9 11l-5 5v4h4l5-5"/><path d="M14 4l6 6-7 7-6-6z"/>',
        draw: '<path d="M3 17c3-6 5-6 7-2s4 4 7-3l2-4"/>',
        shape: '<rect x="3" y="11" width="9" height="9" rx="1"/><circle cx="16" cy="8" r="5"/>',
        note: '<path d="M4 4h16v12H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
        whiteout: '<path d="M7 21l-4-4L14 6l7 7-6 6z"/><path d="M10 21h11"/>',
        redact: '<rect x="3" y="8" width="18" height="8" rx="1.5" fill="currentColor"/>',
        bold: '<path d="M7 5h6a3.5 3.5 0 010 7H7zM7 12h7a3.5 3.5 0 010 7H7z"/>',
        italic: '<path d="M14 5h-4M14 19h-4M14 5l-4 14"/>',
        left: '<path d="M4 6h16M4 10h10M4 14h16M4 18h10"/>',
        center: '<path d="M4 6h16M7 10h10M4 14h16M7 18h10"/>',
        right: '<path d="M4 6h16M10 10h10M4 14h16M10 18h10"/>',
        justify: '<path d="M4 6h16M4 10h16M4 14h16M4 18h16"/>',
        smaller: '<path d="M4 18l4-10 4 10M5.5 14h5M15 13h5"/>',
        larger: '<path d="M4 18l4-10 4 10M5.5 14h5M15 13h5M17.5 10.5v5"/>',
        trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/>',
        replace: '<path d="M4 7h11l-3-3M20 17H9l3 3"/>',
        rotate: '<path d="M20 11a8 8 0 10-2.3 5.7"/><path d="M20 4v7h-7"/>',
        plus: '<path d="M12 5v14M5 12h14"/>',
        duplicate: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 00-1-1H5a1 1 0 00-1 1v10a1 1 0 001 1h3"/>',
        check: '<path d="M5 12l5 5 9-10"/>',
        warning: '<path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
        close: '<path d="M18 6L6 18M6 6l12 12"/>',
        eyedropper: '<path d="M14.5 4.5l5 5M12 7l5 5-8.5 8.5H4v-4.5z"/><path d="M15 3.5a2.1 2.1 0 013 0l2.5 2.5a2.1 2.1 0 010 3L18 11.5"/>'
    };
    const INK = ['#111111', '#e11d48', '#f97316', '#16a34a', '#2563eb', '#7c3aed'];
    const MARKS = ['#ffd400', '#86efac', '#7dd3fc', '#f9a8d4', '#fca5a5'];
    const WIDTHS = [1, 2.5, 5];
    const MARKUP_KINDS = ['highlight', 'underline', 'strikeout'];
    const SHAPES = ['rect', 'ellipse', 'line', 'arrow'];
    const ALIGNS = ['left', 'center', 'right', 'justify'];
    const FAMILIES = ['original', 'sans', 'serif', 'mono'];
    const FAMILY_CSS = {
        sans: 'Helvetica, Arial, sans-serif',
        serif: "'Times New Roman', Times, serif",
        mono: "Consolas, 'Courier New', monospace"
    };
    const KEEPALIVE_MS = 4 * 60 * 1000;
    const PATTERN_KINDS = ['pesel', 'nip', 'regon', 'iban', 'card', 'id_card', 'email', 'phone', 'date'];
    const SANITIZE_KEYS = ['metadata', 'attachments', 'javascript', 'comments', 'links', 'hidden_text', 'fields'];
    const SANITIZE_DEFAULTS = ['metadata', 'attachments', 'javascript'];
    const RESULTS_SHOWN = 200;
    const AI_MODES = ['shorter', 'longer', 'formal', 'simple', 'fix'];
    const LANGUAGES = ['en', 'pl', 'de', 'fr', 'es', 'it', 'pt', 'nl', 'cs', 'sk', 'uk', 'sv', 'da', 'fi', 'nb', 'hu', 'ro', 'tr', 'el', 'ja', 'zh', 'ko'];
    const SNAP_PX = 6;
    const NUDGE_MERGE_MS = 1500;
    const MIN_ZOOM = 0.4;
    const MAX_ZOOM = 5;

    const $ = id => document.getElementById(id);
    const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
    const round = v => Math.round(v * 100) / 100;
    let els = null;
    let s = null;
    let committedDigest = null;

    function icon(name) {
        return `<svg viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;
    }

    function label(key) {
        return `<span data-i18n="${key}">${escapeHtml(t(key))}</span>`;
    }

    function pct(page, [x0, y0, x1, y1]) {
        return `left:${x0 / page.w * 100}%;top:${y0 / page.h * 100}%;width:${(x1 - x0) / page.w * 100}%;height:${(y1 - y0) / page.h * 100}%`;
    }

    function toPt(page, e) {
        const r = page.el.getBoundingClientRect();
        return [round((e.clientX - r.left) / r.width * page.w), round((e.clientY - r.top) / r.height * page.h)];
    }

    function normRect([ax, ay], [bx, by]) {
        return [Math.min(ax, bx), Math.min(ay, by), Math.max(ax, bx), Math.max(ay, by)];
    }

    function hex(color) {
        const m = String(color).match(/\d+(\.\d+)?/g) || [0, 0, 0];
        return '#' + m.slice(0, 3).map(v => Math.round(Number(v)).toString(16).padStart(2, '0')).join('');
    }

    function errorText(body, fallback) {
        const code = body?.error?.code;
        if (code && code in translations.en) return t(code);
        return body?.error?.message || t(fallback);
    }

    function fullBleed(on) {
        const meta = document.querySelector('meta[name="viewport"]');
        if (!meta) return;
        meta.dataset.original ??= meta.content;
        meta.content = on ? `${meta.dataset.original}, viewport-fit=cover` : meta.dataset.original;
    }

    function compact() {
        return window.matchMedia('(max-width: 760px)').matches;
    }

    function postJson(url, body) {
        return fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
            .then(async res => ({ status: res.status, body: await res.json().catch(() => ({})) }));
    }

    function init() {
        if (els) return;
        els = {
            root: $('pdfEditor'), title: $('peTitle'), status: $('peStatus'), close: $('peClose'),
            undo: $('peUndo'), redo: $('peRedo'), zoomIn: $('peZoomIn'), zoomOut: $('peZoomOut'), zoomValue: $('peZoomValue'),
            save: $('peSave'), scroll: $('peScroll'), pages: $('pePages'), dock: $('peDock'), pill: $('pePagePill'),
            context: $('peContext'), tools: $('peTools'), imageInput: $('peImageInput'), notice: $('peNotice'),
            pagesBtn: $('pePagesBtn'), panel: $('pePanel'), thumbs: $('peThumbs'), sheet: $('peSheet'), translateBtn: $('peTranslateBtn'),
            backdrop: $('peBackdrop'), panelClose: $('pePanelClose'), moreBtn: $('peMoreBtn')
        };
        els.tools.innerHTML = TOOLS.map(tool => `
            <button type="button" class="pe-tool" data-tool="${tool}">
                ${icon(tool)}${label(`pe_tool_${tool}`)}
            </button>
        `).join('');
        els.tools.addEventListener('click', e => {
            const btn = e.target.closest('[data-tool]');
            if (btn) setTool(btn.dataset.tool);
        });
        els.close.addEventListener('click', () => close());
        els.save.addEventListener('click', save);
        els.undo.addEventListener('click', undo);
        els.redo.addEventListener('click', redo);
        els.zoomIn.addEventListener('click', () => setZoom(s.zoom * 1.25));
        els.zoomOut.addEventListener('click', () => setZoom(s.zoom / 1.25));
        els.zoomValue.addEventListener('click', () => setZoom(1));
        els.context.addEventListener('pointerdown', e => {
            if (!(e.target instanceof Element) || !e.target.closest('select, input, textarea')) e.preventDefault();
        });
        els.context.addEventListener('click', onContextClick);
        els.notice.addEventListener('click', onNoticeClick);
        els.pagesBtn.addEventListener('click', () => togglePanel());
        els.panelClose.addEventListener('click', () => togglePanel(false));
        els.moreBtn.addEventListener('click', () => s && toggleSheet('menu'));
        els.backdrop.addEventListener('click', () => closeSheet());
        els.sheet.addEventListener('pointerdown', onSheetGrab);
        els.translateBtn.addEventListener('click', () => s && toggleSheet('translate'));
        els.sheet.addEventListener('click', onSheetClick);
        els.sheet.addEventListener('change', onSheetChange);
        els.sheet.addEventListener('input', e => {
            if (e.target.matches('[data-sign="name"]')) {
                s.sign.name = e.target.value;
                els.sheet.querySelectorAll('.pe-sig-font').forEach(el => { el.textContent = s.sign.name || t('pe_sig_name'); });
            }
        });
        els.sheet.addEventListener('keydown', e => {
            if (e.key === 'Enter' && e.target.matches('[data-find="query"]')) {
                e.preventDefault();
                runSearch();
            }
        });
        els.thumbs.addEventListener('click', onThumbClick);
        if (window.Sortable) {
            Sortable.create(els.thumbs, {
                animation: 150, ghostClass: 'pe-thumb-ghost', filter: 'button', preventOnFilter: false, forceFallback: true,
                onEnd: e => {
                    if (!s || e.oldIndex === e.newIndex) return;
                    pushOp({ type: 'page', action: 'move', page: Number(e.item.dataset.id), to: e.newIndex });
                }
            });
        }
        els.context.addEventListener('change', onContextChange);
        els.pages.addEventListener('pointerdown', onPointerDown);
        els.pages.addEventListener('click', onClick);
        els.pages.addEventListener('change', onWidgetChange);
        els.scroll.addEventListener('scroll', () => {
            if (s && !s.scrollFrame) s.scrollFrame = requestAnimationFrame(() => { s && (s.scrollFrame = 0); onScroll(); });
        }, { passive: true });
        els.scroll.addEventListener('touchstart', onTouchStart, { passive: true });
        els.scroll.addEventListener('touchmove', onTouchMove, { passive: false });
        els.scroll.addEventListener('touchend', onTouchEnd, { passive: true });
        els.scroll.addEventListener('touchcancel', onTouchEnd, { passive: true });
        els.scroll.addEventListener('wheel', onWheel, { passive: false });
        els.imageInput.addEventListener('change', onImagePicked);
        window.addEventListener('pointermove', onPointerMove);
        window.addEventListener('pointerup', onPointerUp);
        window.addEventListener('pointercancel', () => cancelDrag());
        window.addEventListener('resize', () => s && layoutPages());
        window.visualViewport?.addEventListener('resize', updateKeyboard);
        window.visualViewport?.addEventListener('scroll', updateKeyboard);
        document.addEventListener('keydown', onKeyDown);
        document.addEventListener('languagechange', () => s && (renderContext(), updateStatus(), renderBanner(), renderSheet(), renderThumbs()));
    }

    async function open(file, { onSave, ops } = {}) {
        init();
        s = {
            fileId: file.file_id, ops: Array.isArray(ops) ? ops.slice() : [], redo: [], zoom: 1, tool: 'edit', pages: [], selection: null, editor: null,
            drag: null, gesture: null, reselect: null, imageTarget: null, note: null, fonts: {}, onSave,
            banner: null, dismissed: new WeakSet(), digest: null, draftTimer: 0, keepalive: 0, restoring: false,
            group: 0, nudge: null, clipboard: null, pasteCount: 0, current: 0, suppressClick: false, sheet: null,
            find: { query: '', whole: false, kinds: new Set(), matches: null, off: new Set(), truncated: false, busy: false },
            scansDismissed: new Set(), ai: { status: null, busy: false, result: null, language: defaultLanguage() },
            translation: null, place: null, sign: { tab: 'draw', color: INK[0], font: 0, name: '', image: null, keep: true, pad: null },
            opts: { ink: INK[1], mark: MARKS[0], width: WIDTHS[1], markup: 'highlight', shape: 'rect', textColor: INK[0], textSize: 12 }
        };
        els.title.textContent = file.filename;
        togglePanel(false);
        els.pages.innerHTML = '';
        els.root.classList.remove('hidden');
        document.body.classList.add('pe-open');
        fullBleed(true);
        setTool('edit');
        updateHistory();
        const session = s;
        try {
            const { body } = await postJson('/api/pdf/edit/pages', { file_id: s.fileId });
            if (!body.success) throw new Error(errorText(body, 'pdf_err_failed'));
            if (s !== session) return;
            s.digest = body.data.digest;
            buildPages(body.data.pages);
            s.keepalive = setInterval(keepAlive, KEEPALIVE_MS);
            if (s.ops.length) storeDraft();
            else offerDraft();
        } catch (err) {
            Toast.error(escapeHtml(err.message));
            close(true);
        }
    }

    function keepAlive() {
        if (!s) return;
        postJson('/api/pdf/edit/keepalive', { file_id: s.fileId, images: PdfDrafts.imageIds(s.ops) }).catch(() => null);
    }

    function storeDraft() {
        if (!s?.digest || s.restoring) return;
        clearTimeout(s.draftTimer);
        const { digest, ops } = s;
        s.draftTimer = setTimeout(() => PdfDrafts.write(digest, ops), 300);
    }

    function offerDraft() {
        PdfDrafts.prune();
        const draft = PdfDrafts.read(s.digest);
        if (!draft) return;
        const time = new Date(draft.savedAt).toLocaleString(i18n.currentLang, { dateStyle: 'short', timeStyle: 'short' });
        showBanner({
            key: 'pe_draft_found', params: { time },
            actions: [
                { key: 'pe_restore', primary: true, run: () => restoreDraft(draft) },
                { key: 'pe_discard', run: () => PdfDrafts.remove(s.digest) }
            ]
        });
    }

    async function restoreDraft(draft) {
        const session = s;
        s.restoring = true;
        const uploads = new Map();
        let missing = 0;
        const ops = [];
        for (const op of draft.ops) {
            if (op.type !== 'image' || !op.file_id) {
                ops.push(op);
                continue;
            }
            if (!uploads.has(op.file_id)) uploads.set(op.file_id, reupload(op.file_id));
            const fileId = await uploads.get(op.file_id);
            if (fileId) ops.push({ ...op, file_id: fileId });
            else missing++;
        }
        if (s !== session) return;
        s.restoring = false;
        s.ops = ops;
        s.redo = [];
        s.group = Math.max(0, ...ops.map(op => op.g || 0));
        applyStructure();
        contentPages(ops).forEach(touch);
        updateHistory();
        if (missing) Toast.warning(escapeHtml(t('pe_restore_partial')));
    }

    async function reupload(fileId) {
        const blob = await PdfDrafts.getImage(fileId);
        if (!blob) return null;
        try {
            const id = await uploadImage(new File([blob], blob.name || 'image.png', { type: blob.type || 'image/png' }));
            await PdfDrafts.putImage(id, blob);
            return id;
        } catch (err) {
            return null;
        }
    }

    function editorChanged(ed) {
        if (!ed) return false;
        const runs = serialize(ed);
        const align = ed.box.style.textAlign || 'left';
        return JSON.stringify(runs) !== ed.initial || !!ed.dx || !!ed.dy || ed.box.dataset.family !== ed.family || align !== ed.align;
    }

    function close(force) {
        if (!s) return;
        if (!force && (s.ops.length || editorChanged(s.editor))) {
            if (!confirm(t('pe_discard_confirm'))) return;
            if (s.digest) PdfDrafts.remove(s.digest);
            clearTimeout(s.draftTimer);
        }
        finishText(false);
        clearTimeout(s.zoomTimer);
        clearInterval(s.keepalive);
        hideBanner();
        closeSheet();
        s = null;
        els.pages.innerHTML = '';
        els.root.classList.add('hidden');
        document.body.classList.remove('pe-open');
        fullBleed(false);
    }

    function digitalOp() {
        return [...s.ops].reverse().find(op => op.type === 'digital_sign') || null;
    }

    function renderDigital(page) {
        if (!page?.layer) return;
        page.layer.querySelectorAll('.pe-dsig').forEach(el => el.remove());
        const op = digitalOp();
        if (op?.page === page.i) page.layer.insertAdjacentHTML('beforeend', `<div class="pe-dsig" style="${pct(page, op.rect)}">${escapeHtml(t('pe_digital_sign'))}</div>`);
    }

    function save() {
        if (!s) return;
        finishText(true);
        if (digitalOp() && s.order.includes(digitalOp().page)) return toggleSheet('certificate');
        commit();
    }

    function commit(extra) {
        const ops = s.ops.slice();
        const onSave = s.onSave;
        committedDigest = s.digest;
        if (!ops.length) return close(true);
        close(true);
        onSave?.(ops, extra);
    }

    function certificateSheet() {
        const op = digitalOp();
        return `${sheetHead('pe_cert_title')}
            <label>${escapeHtml(t('pe_cert_file'))}</label>
            <input type="file" data-cert="file" accept=".p12,.pfx,application/x-pkcs12">
            <input type="password" data-cert="password" autocomplete="off" placeholder="${escapeHtml(t('pe_cert_password'))}" aria-label="${escapeHtml(t('pe_cert_password'))}">
            <input type="text" data-cert="reason" value="${escapeHtml(op?.reason || '')}" placeholder="${escapeHtml(t('pe_cert_reason'))}" aria-label="${escapeHtml(t('pe_cert_reason'))}">
            <input type="text" data-cert="location" value="${escapeHtml(op?.location || '')}" placeholder="${escapeHtml(t('pe_cert_location'))}" aria-label="${escapeHtml(t('pe_cert_location'))}">
            <p class="pe-muted">${escapeHtml(t('pe_cert_note'))}</p>
            <div class="pe-sheet-row"><button type="button" class="btn btn-primary btn-small" data-cert="sign">${icon('shield')} ${escapeHtml(t('pe_cert_sign'))}</button></div>`;
    }

    async function signAndSave(button) {
        const file = els.sheet.querySelector('[data-cert="file"]').files[0];
        if (!file) return;
        const form = new FormData();
        form.append('file', file);
        form.append('password', els.sheet.querySelector('[data-cert="password"]').value);
        button.disabled = true;
        const session = s;
        const body = await fetch('/api/pdf/edit/certificate', { method: 'POST', body: form }).then(r => r.json()).catch(() => ({}));
        if (s !== session) return;
        button.disabled = false;
        if (!body.success) return Toast.error(escapeHtml(errorText(body, 'err_cert_invalid')));
        const op = digitalOp();
        op.reason = els.sheet.querySelector('[data-cert="reason"]').value.trim();
        op.location = els.sheet.querySelector('[data-cert="location"]').value.trim();
        closeSheet();
        commit({ cert_id: body.data.cert_id });
    }

    function makePage(i, w, h) {
        const el = document.createElement('div');
        el.className = 'pe-page';
        el.dataset.page = i;
        el.innerHTML = `<img class="pe-img" alt=""><div class="pe-layer"></div><svg class="pe-live" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"></svg><span class="pe-spinner"></span>`;
        els.pages.appendChild(el);
        return { i, w, h, el, img: el.querySelector('.pe-img'), layer: el.querySelector('.pe-layer'), svg: el.querySelector('.pe-live'), data: null, rev: 0, loadedRev: -1, loadedWidth: 0, token: 0, visible: false };
    }

    function buildPages(sizes) {
        s.base = sizes.length;
        s.pages = sizes.map(([w, h], i) => makePage(i, w, h));
        applyStructure();
        requestAnimationFrame(onScroll);
    }

    function structure() {
        const order = s.pages.slice(0, s.base).map(page => page.i);
        const rotation = {};
        const blanks = {};
        s.ops.forEach(op => {
            if (op.type !== 'page') return;
            const at = order.indexOf(op.page);
            if (op.action === 'insert' && at < 0 && op.page === s.base + Object.keys(blanks).length) {
                blanks[op.page] = op.size;
                order.splice(clamp(op.to, 0, order.length), 0, op.page);
            } else if (at < 0) {
                return;
            } else if (op.action === 'delete' && order.length > 1) {
                order.splice(at, 1);
            } else if (op.action === 'move') {
                order.splice(at, 1);
                order.splice(clamp(op.to, 0, order.length), 0, op.page);
            } else if (op.action === 'rotate') {
                rotation[op.page] = ((rotation[op.page] || 0) + (op.angle || 90)) % 360;
            }
        });
        return { order, rotation, blanks };
    }

    function applyStructure() {
        const { order, rotation, blanks } = structure();
        Object.entries(blanks).forEach(([id, [w, h]]) => {
            const page = s.pages[id];
            if (page && page.w === w && page.h === h) return;
            if (page) page.el.remove();
            s.pages[id] = makePage(Number(id), w, h);
        });
        s.order = order;
        const shown = new Set(order);
        s.pages.forEach(page => {
            page.el.hidden = !shown.has(page.i);
            if (rotation[page.i]) page.el.dataset.rotate = rotation[page.i];
            else delete page.el.dataset.rotate;
        });
        order.forEach(id => els.pages.appendChild(s.pages[id].el));
        if (s.selection && !shown.has(s.selection.page.i)) clearSelection();
        layoutPages();
        renderThumbs();
    }

    function togglePanel(open = els.panel.classList.contains('hidden')) {
        els.panel.classList.toggle('hidden', !open);
        els.pagesBtn.setAttribute('aria-pressed', open ? 'true' : 'false');
        els.root.classList.toggle('panel-open', open);
        if (open) renderThumbs();
    }

    function thumbSrc(page) {
        if (page.img.getAttribute('src')) return page.img.src;
        return page.i < s.base ? `/api/pdf/page/${encodeURIComponent(s.fileId)}/${page.i}?w=200` : '';
    }

    function renderThumbs() {
        if (!s?.order || els.panel.classList.contains('hidden')) return;
        const { rotation } = structure();
        const single = s.order.length < 2;
        els.thumbs.innerHTML = s.order.map((id, position) => {
            const page = s.pages[id];
            const angle = rotation[id] || 0;
            const turned = angle % 180 !== 0;
            const ratio = turned ? page.h / page.w : page.w / page.h;
            const size = ratio >= 1 ? 'width:100%' : `height:100%;width:${ratio * 100}%`;
            const src = thumbSrc(page);
            return `<div class="pe-thumb ${id === s.current ? 'current' : ''}" data-id="${id}">
                <div class="pe-thumb-frame" data-thumb="go">
                    <div class="pe-thumb-page" style="${size};aspect-ratio:${page.w} / ${page.h};transform:rotate(${angle}deg) ${turned ? `scale(${Math.min(ratio, 1 / ratio)})` : ''}">${src ? `<img src="${escapeHtml(src)}" alt="" loading="lazy">` : ''}</div>
                </div>
                <div class="pe-thumb-bar">
                    <span>${position + 1}</span>
                    <button type="button" class="pe-icon-btn" data-thumb="rotate" title="${escapeHtml(t('pe_rotate_page'))}" aria-label="${escapeHtml(t('pe_rotate_page'))}">${icon('rotate')}</button>
                    <button type="button" class="pe-icon-btn" data-thumb="insert" title="${escapeHtml(t('pe_insert_blank'))}" aria-label="${escapeHtml(t('pe_insert_blank'))}">${icon('plus')}</button>
                    <button type="button" class="pe-icon-btn" data-thumb="delete" title="${escapeHtml(t('pe_delete_page'))}" aria-label="${escapeHtml(t('pe_delete_page'))}" ${single ? 'disabled' : ''}>${icon('trash')}</button>
                </div>
            </div>`;
        }).join('');
    }

    function onThumbClick(e) {
        const action = e.target.closest('[data-thumb]')?.dataset.thumb;
        const thumb = e.target.closest('.pe-thumb');
        if (!s || !action || !thumb) return;
        const id = Number(thumb.dataset.id);
        const position = s.order.indexOf(id);
        if (action === 'go') {
            if (compact()) togglePanel(false);
            s.pages[id].el.scrollIntoView({ behavior: compact() ? 'auto' : 'smooth', block: 'start' });
        } else if (action === 'rotate') {
            pushOp({ type: 'page', action: 'rotate', page: id, angle: 90 });
        } else if (action === 'delete' && s.order.length > 1) {
            pushOp({ type: 'page', action: 'delete', page: id });
        } else if (action === 'insert') {
            const page = s.pages[id];
            const blank = s.base + s.ops.filter(op => op.type === 'page' && op.action === 'insert').length;
            pushOp({ type: 'page', action: 'insert', page: blank, to: position + 1, size: [page.w, page.h] });
        }
    }

    function onScroll() {
        if (!s || !s.pages.length) return;
        const view = els.scroll.getBoundingClientRect();
        const order = s.order || [];
        let current = order[0] ?? 0;
        order.forEach(id => {
            const page = s.pages[id];
            const r = page.el.getBoundingClientRect();
            if (r.top <= view.top + view.height / 2) current = page.i;
            page.visible = r.bottom > view.top - 800 && r.top < view.bottom + 800;
            if (page.visible) ensure(page);
            else if ((r.bottom < view.top - 3000 || r.top > view.bottom + 3000) && page.img.hasAttribute('src') && s.editor?.page !== page) unload(page);
        });
        if (current !== s.current) {
            s.current = current;
            els.thumbs.querySelectorAll('.pe-thumb').forEach(el => el.classList.toggle('current', Number(el.dataset.id) === current));
        }
        els.pill.textContent = `${order.indexOf(current) + 1} / ${order.length}`;
    }

    function unload(page) {
        page.img.removeAttribute('src');
        page.el.classList.remove('loading');
        page.inflight = null;
        page.token++;
        page.loadedWidth = 0;
        page.loadedRev = -1;
        page.canvas = null;
    }

    function baseWidth() {
        const pad = window.innerWidth < 640 ? 16 : 64;
        return Math.max(200, Math.min(els.scroll.clientWidth - pad, 1000));
    }

    function layoutPages() {
        const width = baseWidth() * s.zoom;
        s.pages.forEach(page => {
            page.el.style.width = `${width}px`;
            page.el.style.aspectRatio = `${page.w} / ${page.h}`;
            page.el.style.setProperty('--pp', width / page.w);
        });
        els.zoomValue.textContent = `${Math.round(s.zoom * 100)}%`;
        clearTimeout(s.zoomTimer);
        s.zoomTimer = setTimeout(onScroll, 250);
    }

    function setZoom(zoom, focus) {
        if (!s) return;
        zoom = clamp(zoom, MIN_ZOOM, MAX_ZOOM);
        if (Math.abs(zoom - s.zoom) < 0.001) return;
        const rect = els.scroll.getBoundingClientRect();
        const fx = (focus?.x ?? rect.left + rect.width / 2) - rect.left;
        const fy = (focus?.y ?? rect.top + rect.height / 2) - rect.top;
        const ratio = zoom / s.zoom;
        const left = els.scroll.scrollLeft + fx;
        const top = els.scroll.scrollTop + fy;
        s.zoom = zoom;
        layoutPages();
        els.scroll.scrollLeft = left * ratio - fx;
        els.scroll.scrollTop = top * ratio - fy;
    }

    function neededWidth(page) {
        return Math.min(3000, Math.round(page.el.clientWidth * Math.min(window.devicePixelRatio || 1, 2.5)));
    }

    function ensure(page) {
        const need = neededWidth(page) * 0.85;
        if (page.inflight && page.inflight.rev === page.rev && page.inflight.width >= need) return;
        if (page.loadedRev !== page.rev || page.loadedWidth < need) request(page);
    }

    async function request(page) {
        const token = ++page.token;
        const rev = page.rev;
        const width = neededWidth(page);
        const sent = opsFor(page.i);
        page.inflight = { rev, width };
        page.el.classList.add('loading');
        let result;
        try {
            result = await postJson('/api/pdf/edit/page', { file_id: s.fileId, page: page.i, ops: sent, width });
        } catch (err) {
            result = { status: 0, body: {} };
        }
        if (!s || token !== page.token) return;
        page.inflight = null;
        const { status, body } = result;
        if (!body.success) {
            page.el.classList.remove('loading');
            if (status === 404) Toast.error(t('pdf_expired'));
            else Toast.error(escapeHtml(errorText(body, 'err_connection')));
            return;
        }
        const data = body.data;
        if (data.ocr_pending) {
            setTimeout(() => {
                if (s && token === page.token && page.visible) request(page);
            }, 2500);
            return;
        }
        const probe = new Image();
        probe.src = data.image;
        await Promise.race([probe.decode().catch(() => {}), new Promise(r => setTimeout(r, 1500))]);
        if (!s || token !== page.token) return;
        page.img.src = data.image;
        page.data = data;
        page.loadedRev = rev;
        page.loadedWidth = width;
        page.canvas = null;
        page.el.classList.remove('loading');
        page.el.classList.toggle('stale', page.loadedRev !== page.rev);
        page.svg.innerHTML = '';
        renderLayer(page);
        const thumb = els.thumbs.querySelector(`.pe-thumb[data-id="${page.i}"] .pe-thumb-page`);
        if (thumb) thumb.innerHTML = `<img src="${escapeHtml(data.image)}" alt="">`;
        if (data.scanned && !s.banner && !s.scansDismissed.has(page.i) && !s.ops.some(op => op.type === 'ocr' && op.page === page.i)) offerOcr(page);
        Object.keys(data.overflow || {}).forEach(i => {
            const op = sent[Number(i)];
            if (op && !op.fit && !s.dismissed.has(op) && s.ops.includes(op)) offerFit(op);
        });
    }

    function offerOcr(page) {
        showBanner({
            key: 'pe_scan_detected',
            actions: [{ key: 'pe_scan_ocr', primary: true, run: () => {
                Toast.info(escapeHtml(t('pe_scan_wait')));
                pushOp({ type: 'ocr', page: page.i });
            } }],
            dismiss: () => s.scansDismissed.add(page.i)
        });
    }

    function offerFit(op) {
        showBanner({
            key: 'pe_overflow', op,
            actions: [{ key: 'pe_fit', primary: true, run: () => { op.fit = true; touch(op.page); storeDraft(); } }],
            dismiss: () => s.dismissed.add(op)
        });
    }

    function showBanner(banner) {
        s.banner = banner;
        renderBanner();
    }

    function renderBanner() {
        const banner = s?.banner;
        els.notice.classList.toggle('hidden', !banner);
        if (!banner) return;
        els.notice.innerHTML = `${icon('warning')}<span>${escapeHtml(t(banner.key, banner.params))}</span>${banner.actions.map((action, i) => `
            <button type="button" class="pe-chip ${action.primary ? 'active' : ''}" data-notice="${i}">${escapeHtml(t(action.key))}</button>
        `).join('')}<button type="button" class="pe-icon-btn" data-notice="dismiss" aria-label="${escapeHtml(t('close'))}" title="${escapeHtml(t('close'))}">${icon('close')}</button>`;
    }

    function hideBanner() {
        if (s) s.banner = null;
        els.notice.classList.add('hidden');
        els.notice.innerHTML = '';
    }

    function onNoticeClick(e) {
        const action = e.target.closest('[data-notice]')?.dataset.notice;
        const banner = s?.banner;
        if (!action || !banner) return;
        hideBanner();
        if (action === 'dismiss') banner.dismiss?.();
        else banner.actions[Number(action)]?.run();
    }

    function opsFor(index) {
        const blank = index >= s.base;
        return s.ops.filter(op => op.page === index || (blank && op.type === 'page' && op.action === 'insert'));
    }

    function contentPages(ops) {
        return new Set(ops.filter(op => op.type !== 'page' || op.action === 'insert').map(op => op.page));
    }

    function touch(index) {
        const page = s.pages[index];
        if (!page) return;
        page.rev++;
        page.el.classList.add('stale');
        if (page.visible) ensure(page);
    }

    function pushOps(ops) {
        if (!ops.length) return;
        const g = ++s.group;
        ops.forEach(op => {
            op.g = g;
            s.ops.push(op);
        });
        s.redo = [];
        if (ops.some(op => op.type === 'page')) applyStructure();
        contentPages(ops).forEach(touch);
        updateHistory();
    }

    function pushOp(op) {
        pushOps([op]);
    }

    function takeGroup(list) {
        const last = list[list.length - 1];
        if (!last) return [];
        let start = list.length - 1;
        while (last.g !== undefined && start > 0 && list[start - 1].g === last.g) start--;
        return list.splice(start);
    }

    function undo() {
        if (!s) return;
        finishText(false);
        const group = takeGroup(s.ops);
        if (!group.length) return;
        s.redo.push(group);
        clearSelection();
        if (group.some(op => op.type === 'page')) applyStructure();
        contentPages(group).forEach(touch);
        updateHistory();
    }

    function redo() {
        if (!s) return;
        finishText(false);
        const group = s.redo.pop();
        if (!group) return;
        s.ops.push(...group);
        clearSelection();
        if (group.some(op => op.type === 'page')) applyStructure();
        contentPages(group).forEach(touch);
        updateHistory();
    }

    function changeCount() {
        return new Set(s.ops.map((op, i) => op.g ?? `op${i}`)).size;
    }

    function updateHistory() {
        if (s.banner?.op && !s.ops.includes(s.banner.op)) hideBanner();
        storeDraft();
        els.undo.disabled = !s.ops.length;
        els.redo.disabled = !s.redo.length;
        updateStatus();
    }

    function updateStatus() {
        if (s.ops.length) i18n.set(els.status, 'pe_changes', { count: changeCount() });
        else i18n.set(els.status, 'pe_no_changes');
    }

    function updateKeyboard() {
        const vv = window.visualViewport;
        if (!vv || !s) return;
        const keyboard = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
        els.root.style.setProperty('--kb', `${keyboard}px`);
        els.root.classList.toggle('keyboard', keyboard > 80);
    }

    function renderLayer(page) {
        const data = page.data;
        if (!data) return;
        const keep = [...page.layer.children].filter(el => el === s.editor?.wrap || el.classList.contains('pe-note-pop'));
        const parts = [];
        data.images.forEach((image, i) => parts.push(`<div class="pe-obj pe-image ${image.movable === false ? '' : 'movable'}" data-img="${i}" style="${pct(page, image.bbox)}"></div>`));
        data.blocks.forEach((block, i) => parts.push(`<div class="pe-block" data-b="${i}" style="${pct(page, block.bbox)}"></div>`));
        data.annots.forEach((annot, i) => parts.push(`<div class="pe-obj pe-annot ${annot.movable ? 'movable' : ''}" data-an="${i}" style="${pct(page, annot.rect)}"></div>`));
        data.widgets.forEach((widget, i) => parts.push(widgetHtml(page, widget, i)));
        page.layer.innerHTML = parts.join('');
        keep.forEach(el => page.layer.appendChild(el));
        data.widgets.forEach((widget, i) => {
            const input = page.layer.querySelector(`[data-w="${i}"]`);
            if (!input) return;
            if (widget.kind === 'checkbox' || widget.kind === 'radio') input.checked = !!widget.value;
            else input.value = widget.value ?? '';
        });
        renderHits(page);
        renderDigital(page);
        if (s.reselect?.page === page.i) {
            const target = s.reselect;
            s.reselect = null;
            const items = target.items.map(({ kind, rect }) => {
                const list = kind === 'image' ? data.images.map(x => x.bbox) : data.annots.map(x => x.rect);
                return { kind, index: list.findIndex(r => sameRect(r, rect)) };
            }).filter(item => item.index >= 0);
            select(page, items);
            if (target.nudge && s.nudge === target.nudge) s.nudge.selection = s.selection;
        } else if (s.selection?.page === page) {
            clearSelection();
        }
    }

    function widgetHtml(page, widget, i) {
        const style = `${pct(page, widget.rect)};font-size:calc(var(--pp) * ${Math.min(14, Math.max(7, (widget.rect[3] - widget.rect[1]) * 0.62))}px)`;
        const attrs = `class="pe-widget" data-w="${i}" style="${style}" ${widget.readonly ? 'disabled' : ''} aria-label="${escapeHtml(widget.name)}"`;
        if (widget.kind === 'radio') return `<input type="radio" name="pe-radio-${page.i}-${escapeHtml(widget.name)}" ${attrs}>`;
        if (widget.kind === 'checkbox') return `<input type="checkbox" ${attrs}>`;
        if (widget.kind === 'combo' || widget.kind === 'list') {
            const options = widget.options.map(o => {
                const value = Array.isArray(o) ? o[0] : o;
                const text = Array.isArray(o) ? o[1] : o;
                return `<option value="${escapeHtml(value)}">${escapeHtml(text)}</option>`;
            }).join('');
            return `<select data-native ${attrs}><option value=""></option>${options}</select>`;
        }
        if (widget.multiline) return `<textarea ${attrs}></textarea>`;
        return `<input type="text" ${attrs}>`;
    }

    function onWidgetChange(e) {
        const input = e.target.closest?.('.pe-widget');
        if (!input || !s) return;
        const page = pageOf(input);
        const widget = page.data.widgets[Number(input.dataset.w)];
        const value = input.type === 'checkbox' || input.type === 'radio' ? input.checked : input.value;
        if (widget.kind === 'radio') page.data.widgets.forEach(w => { if (w.kind === 'radio' && w.name === widget.name) w.value = false; });
        widget.value = value;
        pushOp({ type: 'form', page: page.i, name: widget.name, rect: widget.rect, value });
    }

    function pageOf(el) {
        const pageEl = el.closest('.pe-page');
        return pageEl ? s.pages[Number(pageEl.dataset.page)] : null;
    }

    function setTool(tool) {
        if (!s) return;
        finishText(true);
        clearSelection();
        closeNote();
        if (tool !== 'redact' && tool !== 'sign') closeSheet();
        if (tool !== 'sign') s.place = null;
        s.tool = tool;
        els.tools.querySelectorAll('[data-tool]').forEach(btn => {
            const active = btn.dataset.tool === tool;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        els.root.dataset.tool = tool;
        renderContext();
    }

    function chip(act, content, { value = '', active = false, title = '' } = {}) {
        return `<button type="button" class="pe-chip ${active ? 'active' : ''}" data-act="${act}" data-value="${escapeHtml(value)}" ${title ? `data-i18n-title="${title}" title="${escapeHtml(t(title))}" aria-label="${escapeHtml(t(title))}"` : ''}>${content}</button>`;
    }

    function swatches(act, colors, current) {
        return `<div class="pe-swatches">${colors.map(c => `<button type="button" class="pe-swatch ${c === current ? 'active' : ''}" data-act="${act}" data-value="${c}" style="--c:${c}" aria-label="${c}"></button>`).join('')}</div>`;
    }

    function widths(current) {
        return `<div class="pe-swatches">${WIDTHS.map(w => `<button type="button" class="pe-width ${w === current ? 'active' : ''}" data-act="width" data-value="${w}" aria-label="${w}"><span style="height:${Math.max(1.5, w * 1.2)}px"></span></button>`).join('')}</div>`;
    }

    function hint(key) {
        return `<p class="pe-hint">${label(key)}</p>`;
    }

    function renderContext() {
        if (!s) return;
        let html = '';
        const o = s.opts;
        if (s.editor) {
            const box = s.editor.box;
            const align = box.style.textAlign || 'left';
            html = `
                ${chip('done', icon('check') + label('pe_done'), { active: true })}
                <select class="pe-select" data-act="family" data-native aria-label="${escapeHtml(t('pe_font'))}">
                    ${FAMILIES.map(f => `<option value="${f}" ${box.dataset.family === f ? 'selected' : ''} data-i18n="pe_font_${f}">${escapeHtml(t(`pe_font_${f}`))}</option>`).join('')}
                </select>
                ${chip('bold', icon('bold'), { title: 'pe_bold' })}
                ${chip('italic', icon('italic'), { title: 'pe_italic' })}
                ${chip('smaller', icon('smaller'), { title: 'pe_smaller' })}
                ${chip('larger', icon('larger'), { title: 'pe_larger' })}
                ${chip('align', icon(align), { title: 'pe_align' })}
                ${swatches('fore', INK, null)}
                ${window.EyeDropper ? chip('eyedropper', icon('eyedropper'), { title: 'pe_eyedropper' }) : ''}
                ${chip('ai', icon('sparkles') + label('pe_ai'), { active: s.sheet === 'ai' })}
                ${chip('delete-text', icon('trash'), { title: 'pe_delete' })}
            `;
        } else if (s.selection) {
            const { page, items } = s.selection;
            const actions = `${chip('duplicate', icon('duplicate'), { title: 'pe_duplicate' })}${chip('delete-object', icon('trash') + label('pe_delete'))}`;
            if (items.length > 1) {
                html = `<span class="pe-count">${escapeHtml(t('pe_selected', { count: items.length }))}</span>${actions}`;
            } else if (items[0].kind === 'image') {
                html = `${chip('replace-image', icon('replace') + label('pe_replace'))}${actions}`;
            } else {
                const annot = itemData(page, items[0]);
                const text = annot.text ? `<p class="pe-note-text">${escapeHtml(annot.text)}</p>` : '';
                html = `${text}${actions}`;
            }
        } else if (s.tool === 'markup') {
            html = MARKUP_KINDS.map(k => chip('markup', label(`pe_markup_${k}`), { value: k, active: o.markup === k })).join('') + swatches('mark', MARKS, o.mark);
        } else if (s.tool === 'draw') {
            html = swatches('ink', INK, o.ink) + widths(o.width);
        } else if (s.tool === 'shape') {
            html = SHAPES.map(k => chip('shape', label(`pe_shape_${k}`), { value: k, active: o.shape === k })).join('') + swatches('ink', INK, o.ink) + widths(o.width);
        } else if (s.tool === 'sign') {
            const active = key => s.place?.key === key;
            const saved = PdfSign.list().map(item => chip('place', `<img src="${escapeHtml(item.url)}" alt="">`, { value: `sig:${item.id}`, active: active(`sig:${item.id}`) })).join('');
            html = hint(s.place?.key === 'digital' ? 'pe_hint_digital' : s.place ? 'pe_hint_place' : 'pe_hint_sign') + saved
                + chip('new-signature', icon('plus') + label('pe_new_signature'), { active: s.sheet === 'sign' })
                + chip('place', icon('date'), { value: 'date', active: active('date'), title: 'pe_date' })
                + chip('place', icon('check'), { value: 'check', active: active('check'), title: 'pe_check' })
                + chip('place', icon('cross'), { value: 'cross', active: active('cross'), title: 'pe_cross' })
                + chip('place', icon('shield') + label('pe_digital_sign'), { value: 'digital', active: active('digital') });
        } else if (s.tool === 'redact') {
            const cleanup = sanitizeOp();
            html = hint('pe_hint_redact') + chip('open-find', label('pe_find_redact'), { active: s.sheet === 'find' })
                + chip('open-sanitize', label('pe_sanitize'), { active: s.sheet === 'sanitize' || !!cleanup });
        } else if (s.tool === 'text') {
            html = hint('pe_hint_text') + swatches('text-color', INK, o.textColor);
        } else {
            html = hint(`pe_hint_${s.tool}`);
        }
        els.context.innerHTML = html;
        els.context.classList.toggle('hidden', !html.trim());
        els.root.classList.toggle('editing', !!s.editor);
    }

    function onContextChange(e) {
        if (e.target.dataset.act === 'family' && s.editor) {
            s.editor.box.dataset.family = e.target.value;
            s.editor.box.focus();
        }
    }

    function onContextClick(e) {
        const btn = e.target.closest('[data-act]');
        if (!btn || !s || btn.tagName === 'SELECT') return;
        const act = btn.dataset.act;
        const value = btn.dataset.value;
        const o = s.opts;
        switch (act) {
            case 'markup': o.markup = value; break;
            case 'shape': o.shape = value; break;
            case 'mark': o.mark = value; break;
            case 'ink': o.ink = value; break;
            case 'width': o.width = Number(value); break;
            case 'text-color': o.textColor = value; o.textColorPicked = true; break;
            case 'bold': formatBox(() => document.execCommand('bold')); return;
            case 'italic': formatBox(() => document.execCommand('italic')); return;
            case 'fore': formatBox(() => document.execCommand('foreColor', false, value)); return;
            case 'eyedropper': pickColor(); return;
            case 'ai': toggleSheet('ai'); return;
            case 'smaller': resizeBox(-1); return;
            case 'larger': resizeBox(1); return;
            case 'align': {
                const box = s.editor.box;
                box.style.textAlign = ALIGNS[(ALIGNS.indexOf(box.style.textAlign || 'left') + 1) % ALIGNS.length];
                break;
            }
            case 'delete-text':
                s.editor.box.innerHTML = '';
                finishText(true);
                return;
            case 'done': finishText(true); return;
            case 'replace-image': {
                const { page, items } = s.selection;
                s.imageTarget = { replace: { page, index: items[0].index } };
                els.imageInput.click();
                return;
            }
            case 'duplicate': duplicateSelection(); return;
            case 'open-find': toggleSheet('find'); return;
            case 'new-signature': toggleSheet('sign'); return;
            case 'place': choosePlacement(value); break;
            case 'open-sanitize': toggleSheet('sanitize'); return;
            case 'delete-object': deleteSelection(); return;
        }
        renderContext();
    }

    function sanitizeOp() {
        const op = [...s.ops].reverse().find(o => o.type === 'sanitize');
        return op && SANITIZE_KEYS.some(key => op.options?.[key]) ? op : null;
    }

    function toggleSheet(kind) {
        if (s.sheet === kind) return closeSheet();
        if (s.sheet) closeSheet();
        s.sheet = kind;
        if ((kind === 'ai' || kind === 'translate') && s.ai.status !== 'ok') checkAi();
        renderSheet();
        renderContext();
        els.sheet.querySelector('input[type="search"]')?.focus();
    }

    function closeSheet() {
        if (!s) return;
        if (s.translation) s.translation.stopped = true;
        s.ai.result = null;
        const wasFind = s.sheet === 'find';
        s.sheet = null;
        els.sheet.classList.add('hidden');
        els.sheet.style.transform = '';
        els.sheet.innerHTML = '';
        els.backdrop.classList.add('hidden');
        els.root.classList.remove('sheet-open');
        if (wasFind) {
            s.find.matches = null;
            s.pages.forEach(renderHits);
        }
        renderContext();
    }

    function renderSheet() {
        if (!s?.sheet) return;
        els.sheet.classList.remove('hidden');
        els.backdrop.classList.remove('hidden');
        els.root.classList.add('sheet-open');
        const views = { find: findSheet, sanitize: sanitizeSheet, sign: signSheet, ai: aiSheet, translate: translateSheet, certificate: certificateSheet, menu: menuSheet };
        els.sheet.innerHTML = views[s.sheet]();
        if (s.sheet === 'sign' && s.sign.tab === 'draw') s.sign.pad = PdfSign.pad(els.sheet.querySelector('.pe-sigpad'), () => s.sign.color);
    }

    function defaultLanguage() {
        const lang = (i18n.currentLang || 'en').slice(0, 2);
        return lang === 'en' ? 'pl' : 'en';
    }

    function languageName(code, locale) {
        try {
            return new Intl.DisplayNames([locale], { type: 'language' }).of(code);
        } catch (err) {
            return code;
        }
    }

    function languageSelect(action) {
        return `<select data-native data-${action}="language" aria-label="${escapeHtml(t('pe_ai_translate'))}">${LANGUAGES.map(code =>
            `<option value="${code}" ${code === s.ai.language ? 'selected' : ''}>${escapeHtml(languageName(code, i18n.currentLang))}</option>`).join('')}</select>`;
    }

    async function checkAi() {
        const session = s;
        const res = await fetch('/api/pdf/edit/ai/status').then(r => r.json()).catch(() => ({}));
        if (s !== session) return;
        s.ai.status = res.data?.status || 'llm_offline';
        renderSheet();
    }

    function aiNotice() {
        if (s.ai.status === null || s.ai.status === 'ok') return '';
        return `<p class="pe-muted">${escapeHtml(t(`err_ai_${s.ai.status}`))}</p>`;
    }

    function aiSheet() {
        const a = s.ai;
        const disabled = a.busy || a.status !== 'ok' ? 'disabled' : '';
        const modes = AI_MODES.map(mode => `<button type="button" class="pe-chip" data-ai="${mode}" ${disabled}>${escapeHtml(t(`pe_ai_${mode}`))}</button>`).join('');
        const result = a.busy ? `<p class="pe-muted">${escapeHtml(t('pe_ai_working'))}</p>` : a.result !== null ? `
            <textarea data-ai="result">${escapeHtml(a.result)}</textarea>
            <div class="pe-sheet-row"><button type="button" class="btn btn-primary btn-small" data-ai="apply">${escapeHtml(t('pe_ai_apply'))}</button></div>` : '';
        return `${sheetHead('pe_ai_title')}${aiNotice()}
            <div class="pe-sheet-row">${modes}</div>
            <div class="pe-sheet-row"><span class="pe-muted">${escapeHtml(t('pe_ai_translate'))}</span>${languageSelect('ai')}<button type="button" class="pe-chip" data-ai="translate" ${disabled}>${icon('sparkles')}</button></div>
            ${result}`;
    }

    function translateSheet() {
        const run = s.translation;
        const disabled = run || s.ai.status !== 'ok' ? 'disabled' : '';
        const progress = run ? `<p>${escapeHtml(t('pe_translate_progress', { page: run.done + 1, total: run.total }))}</p>
            <div class="pe-progress"><span style="width:${Math.round(run.done / run.total * 100)}%"></span></div>
            <div class="pe-sheet-row"><button type="button" class="btn btn-ghost btn-small" data-translate="stop">${escapeHtml(t('pe_stop'))}</button></div>` : '';
        return `${sheetHead('pe_translate_title')}${aiNotice()}
            <div class="pe-sheet-row">${languageSelect('translate')}<button type="button" class="btn btn-primary btn-small" data-translate="run" ${disabled}>${escapeHtml(t('pe_translate_run'))}</button></div>
            ${progress}`;
    }

    async function runAi(mode) {
        const ed = s.editor;
        if (!ed || s.ai.busy) return;
        const text = serialize(ed).map(run => run.t).join('');
        const session = s;
        s.ai.busy = true;
        renderSheet();
        const { body } = await postJson('/api/pdf/edit/ai', { mode, text, language: languageName(s.ai.language, 'en') }).catch(() => ({ body: {} }));
        if (s !== session) return;
        s.ai.busy = false;
        if (body.success) s.ai.result = body.data.text;
        else Toast.error(escapeHtml(errorText(body, 'err_ai_failed')));
        renderSheet();
    }

    function applyAi() {
        const ed = s.editor;
        const text = els.sheet.querySelector('[data-ai="result"]')?.value ?? s.ai.result;
        if (!ed || text === null) return;
        const run = serialize(ed)[0] || {};
        const style = { ...(ed.block?.lines[0]?.spans[0] || {}), ...run, rise: 0 };
        ed.box.innerHTML = text.split('\n').map(line => spanHtml(style, line)).join('<br>');
        closeSheet();
        ed.box.focus({ preventScroll: true });
    }

    async function translateDocument() {
        if (s.translation) return;
        const session = s;
        const language = languageName(s.ai.language, 'en');
        const pages = s.order.slice();
        const run = s.translation = { done: 0, total: pages.length, stopped: false };
        const result = [];
        renderSheet();
        for (const id of pages) {
            if (run.stopped || s !== session) break;
            const { body } = await postJson('/api/pdf/edit/translate', { file_id: s.fileId, ops: s.ops, page: id, language }).catch(() => ({ body: {} }));
            if (s !== session) return;
            if (!body.success) {
                Toast.error(escapeHtml(errorText(body, 'err_ai_failed')));
                break;
            }
            result.push(...body.data.ops);
            run.done++;
            if (s.sheet === 'translate') renderSheet();
        }
        if (s !== session) return;
        s.translation = null;
        if (result.length) {
            pushOps(result);
            Toast.success(escapeHtml(t('pe_translate_done')));
        }
        if (s.sheet === 'translate') closeSheet();
    }

    function menuSheet() {
        const item = (action, iconSvg, key) => `<button type="button" class="pe-menu-item" data-menu="${action}">${iconSvg}<span>${escapeHtml(t(key))}</span></button>`;
        return `<div class="pe-grabber" data-grab></div><div class="pe-menu" data-grab>
            ${item('pages', els.pagesBtn.innerHTML, 'pe_pages')}
            ${item('translate', els.translateBtn.innerHTML, 'pe_translate')}
        </div>`;
    }

    function signSheet() {
        const g = s.sign;
        const tabs = ['draw', 'type', 'image'].map(tab => chip('sig-tab', escapeHtml(t(`pe_sig_${tab}`)), { value: tab, active: g.tab === tab })).join('');
        const colors = swatches('sig-color', [INK[0], INK[4]], g.color);
        let body = '';
        if (g.tab === 'draw') {
            body = `<canvas class="pe-sigpad" aria-label="${escapeHtml(t('pe_sig_draw'))}"></canvas>
                <div class="pe-sheet-row">${colors}<button type="button" class="btn btn-ghost btn-small" data-sign="clear">${escapeHtml(t('pe_sig_clear'))}</button></div>`;
        } else if (g.tab === 'type') {
            body = `<input type="search" data-sign="name" value="${escapeHtml(g.name)}" placeholder="${escapeHtml(t('pe_sig_name'))}" aria-label="${escapeHtml(t('pe_sig_name'))}">
                <div class="pe-sig-fonts">${PdfSign.FONTS.map((font, i) => `<button type="button" class="pe-sig-font ${g.font === i ? 'active' : ''}" data-sign="font" data-index="${i}" style="font-family:${escapeHtml(font)};color:${g.color}">${escapeHtml(g.name || t('pe_sig_name'))}</button>`).join('')}</div>
                <div class="pe-sheet-row">${colors}</div>`;
        } else {
            body = `<div class="pe-sig-preview">${g.image ? `<img src="${escapeHtml(g.image)}" alt="">` : ''}</div>
                <div class="pe-sheet-row"><label class="btn btn-ghost btn-small">${escapeHtml(t('pe_sig_choose'))}<input type="file" data-sign="file" accept="image/png,image/jpeg,image/webp" hidden></label></div>`;
        }
        const saved = PdfSign.list();
        const list = saved.length ? `<div class="pe-muted">${escapeHtml(t('pe_sig_saved'))}</div><div class="pe-sig-saved">${saved.map(item => `
            <div class="pe-sig-item"><img src="${escapeHtml(item.url)}" alt=""><button type="button" data-sign="remove" data-id="${escapeHtml(item.id)}" aria-label="${escapeHtml(t('pe_sig_remove'))}" title="${escapeHtml(t('pe_sig_remove'))}">${icon('close')}</button></div>`).join('')}</div>` : '';
        return `${sheetHead('pe_new_signature')}
            <div class="pe-tabs">${tabs}</div>
            ${body}
            <label><input type="checkbox" data-sign="keep" ${g.keep ? 'checked' : ''}>${escapeHtml(t('pe_sig_keep'))}</label>
            <div class="pe-sheet-row"><button type="button" class="btn btn-primary btn-small" data-sign="use">${escapeHtml(t('pe_sig_use'))}</button></div>
            ${list}`;
    }

    function signatureResult() {
        const g = s.sign;
        if (g.tab === 'draw') return g.pad?.result() || null;
        if (g.tab === 'type') return g.name.trim() ? PdfSign.typed(g.name.trim(), PdfSign.FONTS[g.font], g.color) : null;
        return g.image;
    }

    function choosePlacement(key) {
        if (s.place?.key === key) {
            s.place = null;
            return;
        }
        if (key.startsWith('sig:')) {
            const item = PdfSign.list().find(x => `sig:${x.id}` === key);
            s.place = item ? { key, url: item.url } : null;
        } else {
            s.place = { key };
        }
    }

    async function placeItem(page, p, e) {
        const place = s.place;
        if (place.key === 'check' || place.key === 'cross') {
            const [x, y] = p;
            const points = place.key === 'check'
                ? [[[x - 6, y], [x - 2, y + 4.5], [x + 7, y - 6]]]
                : [[[x - 5, y - 5], [x + 5, y + 5]], [[x + 5, y - 5], [x - 5, y + 5]]];
            pushOp({ type: 'annot', page: page.i, kind: 'ink', points, color: INK[0], width: 1.6 });
            return;
        }
        if (place.key === 'date') {
            beginText(page, null, e);
            s.editor.box.textContent = new Date().toLocaleDateString(i18n.currentLang);
            finishText(true);
            return;
        }
        const session = s;
        try {
            const [file, [w, h]] = await Promise.all([PdfSign.toFile(place.url), PdfSign.size(place.url)]);
            const fileId = await uploadImage(file);
            if (s !== session) return;
            const width = Math.min(160, page.w * 0.4);
            const height = width * h / w;
            const x0 = clamp(p[0] - width / 2, 0, page.w - width);
            const y0 = clamp(p[1] - height / 2, 0, page.h - height);
            const rect = [x0, y0, x0 + width, y0 + height].map(round);
            s.reselect = { page: page.i, items: [{ kind: 'image', rect }] };
            pushOp({ type: 'image', page: page.i, rect, file_id: fileId });
            setTool('edit');
        } catch (err) {
            Toast.error(escapeHtml(err.message || t('err_upload_failed')));
        }
    }

    async function onSignAction(action, target) {
        const g = s.sign;
        if (action === 'clear') return g.pad?.clear();
        if (action === 'font') {
            g.font = Number(target.dataset.index);
            return renderSheet();
        }
        if (action === 'remove') {
            PdfSign.remove(target.dataset.id);
            if (s.place?.key === `sig:${target.dataset.id}`) s.place = null;
            renderSheet();
            return renderContext();
        }
        if (action !== 'use') return;
        const url = signatureResult();
        if (!url) return;
        const item = g.keep ? PdfSign.add(url) : null;
        s.place = { key: item ? `sig:${item.id}` : 'sig:once', url };
        g.image = null;
        closeSheet();
    }

    function sheetHead(key) {
        return `<div class="pe-grabber" data-grab></div><div class="pe-sheet-head" data-grab><span>${escapeHtml(t(key))}</span><button type="button" class="pe-icon-btn" data-sheet="close" aria-label="${escapeHtml(t('close'))}" title="${escapeHtml(t('close'))}">${icon('close')}</button></div>`;
    }

    function findSheet() {
        const f = s.find;
        const chips = PATTERN_KINDS.map(kind => chip('find-kind', escapeHtml(t(`pe_pat_${kind}`)), { value: kind, active: f.kinds.has(kind) })).join('');
        let results = '';
        if (f.busy) {
            results = `<p class="pe-muted">${escapeHtml(t('pe_searching'))}</p>`;
        } else if (f.matches && !f.matches.length) {
            results = `<p class="pe-muted">${escapeHtml(t('pe_no_matches'))}</p>`;
        } else if (f.matches) {
            const chosen = f.matches.length - f.off.size;
            const pages = new Set(f.matches.map(m => m.page)).size;
            results = `<div class="pe-sheet-row"><strong>${escapeHtml(t('pe_matches', { count: f.matches.length }))}</strong><span class="pe-muted">${escapeHtml(t('pe_page_count', { count: pages }))}</span></div>
                <div class="pe-results">${f.matches.slice(0, RESULTS_SHOWN).map((m, i) => `
                    <div class="pe-result">
                        <input type="checkbox" data-find="pick" data-index="${i}" ${f.off.has(i) ? '' : 'checked'} aria-label="${escapeHtml(m.text)}">
                        <span class="pe-result-kind">${escapeHtml(t(`pe_pat_${m.kind}`))}</span>
                        <span class="pe-result-text" title="${escapeHtml(m.text)}">${escapeHtml(m.text)}</span>
                        <button type="button" data-find="go" data-index="${i}">${escapeHtml(t('pe_page_short', { page: s.order.indexOf(m.page) + 1 }))}</button>
                    </div>`).join('')}</div>
                ${f.truncated || f.matches.length > RESULTS_SHOWN ? `<p class="pe-muted">${escapeHtml(t('pe_truncated'))}</p>` : ''}
                <div class="pe-sheet-row"><button type="button" class="btn btn-primary btn-small" data-find="redact" ${chosen ? '' : 'disabled'}>${escapeHtml(t('pe_redact_selected', { count: chosen }))}</button></div>`;
        }
        return `${sheetHead('pe_find_redact')}
            <div class="pe-sheet-row">
                <input type="search" data-find="query" value="${escapeHtml(f.query)}" placeholder="${escapeHtml(t('pe_find_placeholder'))}" aria-label="${escapeHtml(t('pe_find_placeholder'))}">
                <button type="button" class="btn btn-ghost btn-small" data-find="run">${escapeHtml(t('pe_find'))}</button>
            </div>
            <div class="pe-sheet-row"><label><input type="checkbox" data-find="whole" ${f.whole ? 'checked' : ''}>${escapeHtml(t('pe_whole_word'))}</label></div>
            <div class="pe-muted">${escapeHtml(t('pe_patterns'))}</div>
            <div class="pe-sheet-row">${chips}</div>
            ${results}`;
    }

    function sanitizeSheet() {
        const current = sanitizeOp()?.options;
        const checked = key => current ? !!current[key] : SANITIZE_DEFAULTS.includes(key);
        return `${sheetHead('pe_sanitize_title')}
            ${SANITIZE_KEYS.map(key => `<label><input type="checkbox" data-clean="${key}" ${checked(key) ? 'checked' : ''}>${escapeHtml(t(`pe_s_${key}`))}</label>`).join('')}
            <div class="pe-sheet-row"><button type="button" class="btn btn-primary btn-small" data-clean-apply>${escapeHtml(t('pe_apply'))}</button></div>`;
    }

    async function runSearch() {
        const f = s.find;
        const input = els.sheet.querySelector('[data-find="query"]');
        if (input) f.query = input.value;
        if (!f.query.trim() && !f.kinds.size) return;
        const session = s;
        f.busy = true;
        renderSheet();
        const { body } = await postJson('/api/pdf/edit/search', {
            file_id: s.fileId, ops: s.ops, query: f.query, patterns: [...f.kinds], whole_word: f.whole
        }).catch(() => ({ body: {} }));
        if (s !== session) return;
        f.busy = false;
        if (!body.success) {
            f.matches = null;
            Toast.error(escapeHtml(errorText(body, 'err_connection')));
        } else {
            f.matches = body.data.matches;
            f.truncated = body.data.truncated;
            f.off = new Set();
        }
        renderSheet();
        s.pages.forEach(renderHits);
    }

    function renderHits(page) {
        if (!page?.layer) return;
        page.layer.querySelectorAll('.pe-hit').forEach(el => el.remove());
        const matches = s.find.matches || [];
        const html = matches.flatMap((m, i) => m.page !== page.i ? [] : m.rects.map(rect =>
            `<div class="pe-hit ${s.find.off.has(i) ? 'off' : ''}" data-hit="${i}" style="${pct(page, rect)}"></div>`)).join('');
        if (html) page.layer.insertAdjacentHTML('beforeend', html);
    }

    function redactMatches() {
        const f = s.find;
        const byPage = new Map();
        f.matches.forEach((m, i) => {
            if (f.off.has(i)) return;
            if (!byPage.has(m.page)) byPage.set(m.page, []);
            byPage.get(m.page).push(...m.rects);
        });
        if (!byPage.size) return;
        pushOps([...byPage].map(([page, rects]) => ({ type: 'redact', page, rects })));
        closeSheet();
    }

    function onSheetGrab(e) {
        if (!compact() || !e.target.closest('[data-grab]') || e.target.closest('button, input, select')) return;
        const sheet = els.sheet;
        const startY = e.clientY;
        let dy = 0;
        sheet.setPointerCapture(e.pointerId);
        sheet.style.transition = 'none';
        const move = ev => {
            dy = Math.max(0, ev.clientY - startY);
            sheet.style.transform = `translateY(${dy}px)`;
        };
        const end = () => {
            sheet.removeEventListener('pointermove', move);
            sheet.removeEventListener('pointerup', end);
            sheet.removeEventListener('pointercancel', end);
            sheet.style.transition = '';
            if (dy > 90) closeSheet();
            else sheet.style.transform = '';
        };
        sheet.addEventListener('pointermove', move);
        sheet.addEventListener('pointerup', end);
        sheet.addEventListener('pointercancel', end);
    }

    function onSheetClick(e) {
        if (!s) return;
        if (e.target.closest('[data-sheet="close"]')) return closeSheet();
        const tab = e.target.closest('[data-act="sig-tab"]');
        if (tab) {
            s.sign.tab = tab.dataset.value;
            return renderSheet();
        }
        const color = e.target.closest('[data-act="sig-color"]');
        if (color) {
            s.sign.color = color.dataset.value;
            if (s.sign.tab === 'type') renderSheet();
            else els.sheet.querySelectorAll('[data-act="sig-color"]').forEach(el => el.classList.toggle('active', el === color));
            return;
        }
        const menu = e.target.closest('[data-menu]')?.dataset.menu;
        if (menu) {
            closeSheet();
            return menu === 'pages' ? togglePanel(true) : toggleSheet('translate');
        }
        const certButton = e.target.closest('button[data-cert="sign"]');
        if (certButton) return signAndSave(certButton);
        const aiAction = e.target.closest('button[data-ai]')?.dataset.ai;
        if (aiAction === 'apply') return applyAi();
        if (aiAction) return runAi(aiAction);
        const translateAction = e.target.closest('button[data-translate]')?.dataset.translate;
        if (translateAction === 'run') return translateDocument();
        if (translateAction === 'stop' && s.translation) {
            s.translation.stopped = true;
            return;
        }
        const signAction = e.target.closest('[data-sign]');
        if (signAction && e.type === 'click' && signAction.tagName === 'BUTTON') return onSignAction(signAction.dataset.sign, signAction);
        if (e.target.closest('[data-clean-apply]')) {
            const options = {};
            els.sheet.querySelectorAll('[data-clean]').forEach(box => { options[box.dataset.clean] = box.checked; });
            pushOp({ type: 'sanitize', page: -1, options });
            closeSheet();
            if (SANITIZE_KEYS.some(key => options[key])) Toast.info(escapeHtml(t('pe_sanitize_on')));
            return;
        }
        const kindChip = e.target.closest('[data-act="find-kind"]');
        if (kindChip) {
            const kinds = s.find.kinds;
            const kind = kindChip.dataset.value;
            kinds.has(kind) ? kinds.delete(kind) : kinds.add(kind);
            s.find.query = els.sheet.querySelector('[data-find="query"]')?.value || '';
            kindChip.classList.toggle('active', kinds.has(kind));
            return;
        }
        const action = e.target.closest('[data-find]')?.dataset.find;
        if (action === 'run') runSearch();
        else if (action === 'redact') redactMatches();
        else if (action === 'go') {
            const match = s.find.matches[Number(e.target.closest('[data-index]').dataset.index)];
            const page = s.pages[match.page];
            page.el.scrollIntoView({ behavior: 'smooth', block: 'center' });
            setTimeout(() => page.layer.querySelectorAll(`[data-hit="${s.find.matches.indexOf(match)}"]`).forEach(el => {
                el.classList.remove('flash');
                void el.offsetWidth;
                el.classList.add('flash');
            }), 350);
        }
    }

    function onSheetChange(e) {
        if (!s) return;
        if (e.target.dataset.sign === 'keep') s.sign.keep = e.target.checked;
        if (e.target.dataset.ai === 'language' || e.target.dataset.translate === 'language') s.ai.language = e.target.value;
        if (e.target.dataset.sign === 'file' && e.target.files[0]) {
            PdfSign.cleanImage(e.target.files[0]).then(url => {
                if (!s) return;
                s.sign.image = url;
                renderSheet();
            }).catch(() => Toast.error(escapeHtml(t('err_upload_failed'))));
        }
        const action = e.target.dataset.find;
        if (action === 'whole') s.find.whole = e.target.checked;
        if (action === 'pick') {
            const index = Number(e.target.dataset.index);
            e.target.checked ? s.find.off.delete(index) : s.find.off.add(index);
            s.pages.forEach(renderHits);
            const chosen = s.find.matches.length - s.find.off.size;
            const button = els.sheet.querySelector('[data-find="redact"]');
            button.textContent = t('pe_redact_selected', { count: chosen });
            button.disabled = !chosen;
        }
    }

    function sameRect(a, b, tolerance = 3) {
        return a.every((v, k) => Math.abs(v - b[k]) < tolerance);
    }

    function shiftRect([x0, y0, x1, y1], dx, dy) {
        return [x0 + dx, y0 + dy, x1 + dx, y1 + dy].map(round);
    }

    function bounds(rects) {
        return rects.reduce((a, r) => [Math.min(a[0], r[0]), Math.min(a[1], r[1]), Math.max(a[2], r[2]), Math.max(a[3], r[3])]);
    }

    function itemData(page, item) {
        return item.kind === 'image' ? page.data.images[item.index] : page.data.annots[item.index];
    }

    function itemRect(page, item) {
        const data = itemData(page, item);
        return item.kind === 'image' ? data.bbox : data.rect;
    }

    function itemMovable(page, item) {
        const data = itemData(page, item);
        return item.kind === 'image' ? data.movable !== false : !!data.movable;
    }

    function objectEl(page, { kind, index }) {
        return page.layer.querySelector(kind === 'image' ? `[data-img="${index}"]` : `[data-an="${index}"]`);
    }

    function ready(page) {
        return page.data && page.loadedRev === page.rev;
    }

    function select(page, items, mode = 'replace') {
        const keep = mode !== 'replace' && s.selection?.page === page ? s.selection.items.map(({ kind, index }) => ({ kind, index })) : [];
        let next = keep;
        items.forEach(item => {
            const at = next.findIndex(x => x.kind === item.kind && x.index === item.index);
            if (at >= 0 && mode === 'toggle') next = next.filter((_, i) => i !== at);
            else if (at < 0) next = [...next, { kind: item.kind, index: item.index }];
        });
        clearSelection(true);
        const resolved = next.map(item => ({ ...item, el: objectEl(page, item) })).filter(item => item.el);
        resolved.forEach(item => item.el.classList.add('selected'));
        if (resolved.length === 1 && resolved[0].kind === 'image' && itemMovable(page, resolved[0])) {
            resolved[0].el.insertAdjacentHTML('beforeend', '<span class="pe-handle"></span>');
        }
        s.selection = resolved.length ? { page, items: resolved } : null;
        renderContext();
    }

    function clearSelection(silent) {
        if (!s?.selection) return;
        s.selection.items.forEach(({ el }) => {
            el.classList.remove('selected');
            el.querySelector('.pe-handle')?.remove();
        });
        s.selection = null;
        if (!silent) renderContext();
    }

    function selectAll() {
        const page = s.pages[s.current];
        if (!page?.data) return;
        select(page, [
            ...page.data.images.map((_, index) => ({ kind: 'image', index })),
            ...page.data.annots.map((_, index) => ({ kind: 'annot', index }))
        ]);
    }

    function deleteOp(page, item) {
        const data = itemData(page, item);
        if (item.kind === 'image') return { type: 'image', page: page.i, xref: data.xref, remove: data.bbox };
        return { type: 'annot_edit', page: page.i, target: data.rect, delete: true };
    }

    function moveOp(page, item, origin, rect) {
        if (item.kind === 'image') return { type: 'image', page: page.i, xref: itemData(page, item).xref, remove: origin, rect };
        return { type: 'annot_edit', page: page.i, target: origin, rect };
    }

    function deleteSelection() {
        const sel = s.selection;
        if (!sel || !ready(sel.page)) return;
        clearSelection();
        pushOps(sel.items.map(item => deleteOp(sel.page, item)));
    }

    function nudge(dx, dy) {
        const sel = s.selection;
        if (!sel) return;
        const page = sel.page;
        const last = s.nudge;
        if (last && last.selection === sel && Date.now() - last.at < NUDGE_MERGE_MS && s.ops.includes(last.ops[0])) {
            last.ops.forEach((op, i) => {
                op.rect = shiftRect(op.rect, dx, dy);
                if (sel.items[i]) sel.items[i].el.setAttribute('style', pct(page, op.rect));
            });
            last.at = Date.now();
            s.redo = [];
            s.reselect = { page: page.i, items: last.ops.map((op, i) => ({ kind: last.kinds[i], rect: op.rect })), nudge: last };
            touch(page.i);
            updateHistory();
            return;
        }
        if (!ready(page)) return;
        const items = sel.items.filter(item => itemMovable(page, item));
        if (!items.length) return;
        const ops = items.map(item => {
            const origin = itemRect(page, item).slice();
            return moveOp(page, item, origin, shiftRect(origin, dx, dy));
        });
        items.forEach((item, i) => item.el.setAttribute('style', pct(page, ops[i].rect)));
        s.nudge = { selection: sel, at: Date.now(), ops, kinds: items.map(item => item.kind) };
        s.reselect = { page: page.i, items: ops.map((op, i) => ({ kind: items[i].kind, rect: op.rect })), nudge: s.nudge };
        pushOps(ops);
    }

    function insertedImage(page, rect) {
        let current = rect;
        for (let i = s.ops.length - 1; i >= 0; i--) {
            const op = s.ops[i];
            if (op.type !== 'image' || op.page !== page.i || !op.rect || !sameRect(op.rect, current, 1.5)) continue;
            if (op.file_id) return op.file_id;
            if (op.source || !op.remove) return null;
            current = op.remove;
        }
        return null;
    }

    function copySelection() {
        const sel = s.selection;
        if (!sel || !ready(sel.page)) return false;
        s.clipboard = sel.items.map(item => {
            const data = itemData(sel.page, item);
            const rect = itemRect(sel.page, item).slice();
            if (item.kind === 'annot') return { kind: 'annot', rect, page: sel.page.i };
            const fileId = insertedImage(sel.page, rect);
            if (fileId) return { kind: 'image', rect, file_id: fileId, page: sel.page.i };
            return { kind: 'image', rect, xref: data.stable ? data.xref : 0, page: sel.page.i };
        });
        s.pasteCount = 0;
        return true;
    }

    function paste() {
        const page = s.pages[s.current];
        if (!s.clipboard?.length || !page || !ready(page)) return;
        const offset = s.clipboard.every(c => c.page === page.i) ? 12 * ++s.pasteCount : 0;
        const ops = s.clipboard.map(c => {
            const rect = shiftRect(c.rect, offset, offset);
            if (c.kind === 'image') {
                if (c.file_id) return { type: 'image', page: page.i, rect, file_id: c.file_id };
                if (c.xref) return { type: 'image', page: page.i, rect, source: { xref: c.xref } };
                if (c.page === page.i) return { type: 'image', page: page.i, rect, source: { bbox: c.rect } };
                return null;
            }
            if (c.page === page.i && page.data.annots.some(a => sameRect(a.rect, c.rect))) return { type: 'annot_edit', page: page.i, target: c.rect, copy: [offset, offset] };
            return null;
        });
        const usable = ops.filter(Boolean);
        if (usable.length < ops.length) Toast.info(escapeHtml(t('pe_paste_partial')));
        if (!usable.length) return;
        s.reselect = { page: page.i, items: usable.map(op => ({ kind: op.type === 'image' ? 'image' : 'annot', rect: op.rect || shiftRect(op.target, offset, offset) })) };
        clearSelection();
        pushOps(usable);
    }

    function duplicateSelection() {
        const sel = s.selection;
        if (!sel) return;
        const previous = s.clipboard;
        const count = s.pasteCount;
        s.current = sel.page.i;
        if (copySelection()) paste();
        if (previous) {
            s.clipboard = previous;
            s.pasteCount = count;
        }
    }

    function snapTargets(page, skip) {
        const xs = [0, page.w / 2, page.w];
        const ys = [0, page.h / 2, page.h];
        const add = ([x0, y0, x1, y1]) => {
            xs.push(x0, (x0 + x1) / 2, x1);
            ys.push(y0, (y0 + y1) / 2, y1);
        };
        page.data.images.forEach((image, i) => skip.has(`image:${i}`) || add(image.bbox));
        page.data.annots.forEach((annot, i) => skip.has(`annot:${i}`) || add(annot.rect));
        page.data.blocks.forEach(block => add(block.bbox));
        return { xs, ys };
    }

    function snapAxis(values, targets, tolerance) {
        let best = null;
        values.forEach(v => targets.forEach(target => {
            const delta = target - v;
            if (Math.abs(delta) <= tolerance && (!best || Math.abs(delta) < Math.abs(best.delta))) best = { delta, at: target };
        }));
        return best;
    }

    function showGuides(page, guides) {
        page.svg.querySelectorAll('.pe-guide').forEach(el => el.remove());
        const ns = 'http://www.w3.org/2000/svg';
        guides.forEach(([x1, y1, x2, y2]) => {
            const line = document.createElementNS(ns, 'line');
            line.setAttribute('class', 'pe-guide');
            Object.entries({ x1, y1, x2, y2 }).forEach(([k, v]) => line.setAttribute(k, v));
            page.svg.appendChild(line);
        });
    }

    function snapMove(d, dx, dy, free) {
        const box = shiftRect(bounds(d.items.map(item => item.origin)), dx, dy);
        if (free) {
            showGuides(d.page, []);
            return [dx, dy];
        }
        const tolerance = SNAP_PX / (d.page.el.clientWidth / d.page.w);
        const sx = snapAxis([box[0], (box[0] + box[2]) / 2, box[2]], d.targets.xs, tolerance);
        const sy = snapAxis([box[1], (box[1] + box[3]) / 2, box[3]], d.targets.ys, tolerance);
        const guides = [];
        if (sx) guides.push([sx.at, 0, sx.at, d.page.h]);
        if (sy) guides.push([0, sy.at, d.page.w, sy.at]);
        showGuides(d.page, guides);
        return [dx + (sx?.delta || 0), dy + (sy?.delta || 0)];
    }

    function onClick(e) {
        if (s?.suppressClick) {
            s.suppressClick = false;
            return;
        }
        if (!s || s.tool !== 'edit' || s.gesture || e.shiftKey) return;
        const blockEl = e.target.closest?.('.pe-block');
        if (!blockEl) return;
        const page = pageOf(blockEl);
        beginText(page, page.data.blocks[Number(blockEl.dataset.b)], e);
    }

    function onPointerDown(e) {
        if (!s || s.gesture || !(e.target instanceof Element)) return;
        if (e.pointerType === 'mouse' && e.button !== 0) return;
        if (!e.isPrimary || s.drag) return cancelDrag();
        const inEditor = e.target.closest('.pe-text-wrap, .pe-note-pop');
        if (s.editor && !inEditor) finishText(true);
        if (inEditor) {
            if (e.target.closest('.pe-grip')) startTextMove(e);
            return;
        }
        if (s.note && !e.target.closest('.pe-note-pop')) closeNote();
        const page = pageOf(e.target);
        if (!page || !page.data) return;
        const p = toPt(page, e);
        if (s.tool === 'edit') {
            const obj = e.target.closest('.pe-obj');
            if (e.target.closest('.pe-widget')) return clearSelection();
            if (!obj) {
                const ns = 'http://www.w3.org/2000/svg';
                const el = document.createElementNS(ns, 'rect');
                el.setAttribute('class', 'pe-marquee');
                page.svg.appendChild(el);
                s.drag = { type: 'marquee', page, start: p, end: p, el, additive: e.shiftKey, moved: false };
                return;
            }
            const kind = obj.classList.contains('pe-image') ? 'image' : 'annot';
            const item = { kind, index: Number(kind === 'image' ? obj.dataset.img : obj.dataset.an) };
            const selected = s.selection?.page === page && s.selection.items.some(x => x.el === obj);
            if (e.shiftKey) {
                select(page, [item], 'toggle');
                e.preventDefault();
                return;
            }
            if (!selected) select(page, [item]);
            if (!ready(page)) return;
            const items = s.selection.items.filter(x => itemMovable(page, x)).map(x => ({ ...x, origin: itemRect(page, x).slice() }));
            if (!items.length) return;
            const resize = !!e.target.closest('.pe-handle');
            const skip = new Set(items.map(x => `${x.kind}:${x.index}`));
            s.drag = { type: resize ? 'resize' : 'move', page, items: resize ? items.filter(x => x.el === obj) : items, start: p, moved: false, targets: snapTargets(page, skip) };
            e.preventDefault();
            return;
        }
        e.preventDefault();
        if (s.tool === 'text') return beginText(page, null, e);
        if (s.tool === 'sign') {
            if (!s.place) return toggleSheet('sign');
            if (s.place.key !== 'digital') return placeItem(page, p, e);
        }
        if (s.tool === 'image') {
            s.imageTarget = { page, at: p };
            els.imageInput.click();
            return;
        }
        if (s.tool === 'note') return openNote(page, p);
        const ns = 'http://www.w3.org/2000/svg';
        const shape = document.createElementNS(ns, s.tool === 'draw' ? 'polyline' : 'g');
        page.svg.appendChild(shape);
        s.drag = { type: s.tool === 'sign' ? 'digital' : s.tool, page, start: p, end: p, points: [p], el: shape, word: s.tool === 'markup' ? nearestWord(page, p) : -1 };
        drawLive();
    }

    function onPointerMove(e) {
        if (!s?.drag || s.gesture) return;
        const d = s.drag;
        const p = toPt(d.page, e);
        if (d.type === 'move' || d.type === 'resize') {
            const dx = p[0] - d.start[0];
            const dy = p[1] - d.start[1];
            if (!d.moved && Math.hypot(dx, dy) < 2) return;
            d.moved = true;
            if (d.type === 'move') {
                const [sx, sy] = snapMove(d, dx, dy, e.altKey);
                d.items.forEach(item => {
                    item.rect = shiftRect(item.origin, sx, sy);
                    item.el.setAttribute('style', pct(d.page, item.rect));
                });
            } else {
                const item = d.items[0];
                const [x0, y0, x1, y1] = item.origin;
                const w = Math.max(8, x1 - x0 + dx);
                item.rect = [x0, y0, x0 + w, y0 + w * (y1 - y0) / (x1 - x0)];
                item.el.setAttribute('style', pct(d.page, item.rect));
            }
            return;
        }
        if (d.type === 'marquee') {
            d.end = p;
            d.moved ||= Math.hypot(p[0] - d.start[0], p[1] - d.start[1]) > 3;
            const [x0, y0, x1, y1] = normRect(d.start, d.end);
            Object.entries({ x: x0, y: y0, width: x1 - x0, height: y1 - y0 }).forEach(([k, v]) => d.el.setAttribute(k, v));
            return;
        }
        if (d.type === 'textmove') {
            s.editor.dx = d.dx + p[0] - d.start[0];
            s.editor.dy = d.dy + p[1] - d.start[1];
            placeEditor(s.editor);
            return;
        }
        d.end = p;
        if (d.type === 'draw') {
            const last = d.points[d.points.length - 1];
            if (Math.hypot(p[0] - last[0], p[1] - last[1]) < 0.8) return;
            d.points.push(p);
        }
        drawLive();
    }

    function onPointerUp() {
        if (!s?.drag) return;
        const d = s.drag;
        s.drag = null;
        const page = d.page;
        if (d.type === 'move' || d.type === 'resize') {
            showGuides(page, []);
            if (!d.moved) return;
            const ops = d.items.map(item => moveOp(page, item, item.origin, item.rect.map(round)));
            s.reselect = { page: page.i, items: d.items.map((item, i) => ({ kind: item.kind, rect: ops[i].rect })) };
            pushOps(ops);
            return;
        }
        if (d.type === 'marquee') {
            d.el.remove();
            if (!d.moved) {
                if (!d.additive) clearSelection();
                return;
            }
            s.suppressClick = true;
            const area = normRect(d.start, d.end);
            const inside = r => r[0] < area[2] && r[2] > area[0] && r[1] < area[3] && r[3] > area[1];
            const items = [
                ...page.data.images.map((image, index) => ({ kind: 'image', index, rect: image.bbox })),
                ...page.data.annots.map((annot, index) => ({ kind: 'annot', index, rect: annot.rect }))
            ].filter(item => inside(item.rect));
            if (items.length || !d.additive) select(page, items, d.additive ? 'add' : 'replace');
            return;
        }
        if (d.type === 'textmove') return;
        const rect = normRect(d.start, d.end).map(round);
        const big = rect[2] - rect[0] > 3 || rect[3] - rect[1] > 3;
        if (d.type === 'draw') {
            if (d.points.length > 1) pushOp({ type: 'annot', page: page.i, kind: 'ink', points: [d.points], color: s.opts.ink, width: s.opts.width });
            else d.el.remove();
        } else if (d.type === 'markup') {
            const rects = markupRects(page, d);
            if (rects.length) pushOp({ type: 'annot', page: page.i, kind: s.opts.markup, rects, color: markColor() });
            else d.el.remove();
        } else if (d.type === 'shape' && big) {
            const kind = s.opts.shape;
            const r = kind === 'line' || kind === 'arrow' ? [...d.start, ...d.end] : rect;
            pushOp({ type: 'annot', page: page.i, kind, rect: r, color: s.opts.ink, width: s.opts.width });
        } else if ((d.type === 'whiteout' || d.type === 'redact') && big) {
            pushOp({ type: d.type, page: page.i, rect });
        } else if (d.type === 'digital' && rect[2] - rect[0] > 20 && rect[3] - rect[1] > 12) {
            d.el.remove();
            pushOp({ type: 'digital_sign', page: page.i, rect });
            setTool('edit');
        } else {
            d.el.remove();
        }
    }

    function cancelDrag() {
        if (!s?.drag) return;
        const d = s.drag;
        if (d.el?.ownerSVGElement) d.el.remove();
        if (d.type === 'move' || d.type === 'resize') {
            d.items.forEach(item => item.el.setAttribute('style', pct(d.page, item.origin)));
            showGuides(d.page, []);
        }
        s.drag = null;
    }

    function drawLive() {
        const d = s.drag;
        const o = s.opts;
        const [x0, y0, x1, y1] = normRect(d.start, d.end);
        if (d.type === 'draw') {
            d.el.setAttribute('points', d.points.map(p => p.join(',')).join(' '));
            d.el.setAttribute('style', `fill:none;stroke:${o.ink};stroke-width:${o.width};stroke-linecap:round;stroke-linejoin:round`);
        } else if (d.type === 'markup') {
            const rects = markupRects(d.page, d);
            d.el.innerHTML = rects.map(([a, b, c, e]) => {
                if (o.markup === 'highlight') return `<rect x="${a}" y="${b}" width="${c - a}" height="${e - b}" fill="${o.mark}" opacity="0.45"/>`;
                const y = o.markup === 'underline' ? e - 0.5 : (b + e) / 2;
                return `<line x1="${a}" y1="${y}" x2="${c}" y2="${y}" stroke="${markColor()}" stroke-width="1.2"/>`;
            }).join('');
        } else if (d.type === 'shape') {
            const style = `fill:none;stroke:${o.ink};stroke-width:${o.width}`;
            if (o.shape === 'rect') d.el.innerHTML = `<rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" style="${style}"/>`;
            else if (o.shape === 'ellipse') d.el.innerHTML = `<ellipse cx="${(x0 + x1) / 2}" cy="${(y0 + y1) / 2}" rx="${(x1 - x0) / 2}" ry="${(y1 - y0) / 2}" style="${style}"/>`;
            else d.el.innerHTML = `<line x1="${d.start[0]}" y1="${d.start[1]}" x2="${d.end[0]}" y2="${d.end[1]}" style="${style};stroke-linecap:round"/>`;
        } else {
            const fill = d.type === 'redact' ? '#000' : d.type === 'digital' ? 'rgba(37,99,235,0.08)' : '#fff';
            d.el.innerHTML = `<rect x="${x0}" y="${y0}" width="${x1 - x0}" height="${y1 - y0}" fill="${fill}" stroke="#2563eb" stroke-width="0.6" stroke-dasharray="3 2"/>`;
        }
    }

    function markColor() {
        return s.opts.markup !== 'highlight' && s.opts.mark === MARKS[0] ? '#e11d48' : s.opts.mark;
    }

    function nearestWord(page, [x, y]) {
        const words = page.data.words;
        let best = -1;
        let score = Infinity;
        words.forEach((w, i) => {
            const dx = Math.max(w[0] - x, 0, x - w[2]);
            const dy = Math.max(w[1] - y, 0, y - w[3]);
            const d = dx * dx + dy * dy * 4;
            if (d < score) { score = d; best = i; }
        });
        return score < 400 ? best : -1;
    }

    function markupRects(page, d) {
        const words = page.data.words;
        const end = nearestWord(page, d.end);
        if (d.word < 0 || end < 0) {
            const r = normRect(d.start, d.end);
            return r[2] - r[0] > 3 && r[3] - r[1] > 3 ? [r] : [];
        }
        const rects = [];
        let key = null;
        for (let i = Math.min(d.word, end); i <= Math.max(d.word, end); i++) {
            const w = words[i];
            const k = `${w[4]}-${w[5]}`;
            const last = rects[rects.length - 1];
            if (k === key && last) {
                last[0] = Math.min(last[0], w[0]); last[1] = Math.min(last[1], w[1]);
                last[2] = Math.max(last[2], w[2]); last[3] = Math.max(last[3], w[3]);
            } else {
                rects.push(w.slice(0, 4));
                key = k;
            }
        }
        return rects;
    }

    function ensureFont(span) {
        if (!span.f || s.fonts[span.f] !== undefined || !window.FontFace) return;
        s.fonts[span.f] = null;
        const face = new FontFace(`pef-${span.f}`, `url(/api/pdf/edit/font/${encodeURIComponent(s.fileId)}/${span.f})`, {
            weight: span.b ? '700' : '400', style: span.i ? 'italic' : 'normal'
        });
        face.load().then(f => { document.fonts.add(f); s && (s.fonts[span.f] = true); }).catch(() => { s && (s.fonts[span.f] = false); });
    }

    function familyCss(span) {
        const names = (span.n || []).map(n => `"${String(n).replace(/["\\]/g, '')}"`);
        return [span.f ? `"pef-${span.f}"` : '', ...names, FAMILY_CSS[span.k] || FAMILY_CSS.sans].filter(Boolean).join(', ');
    }

    function spanHtml(span, text) {
        ensureFont(span);
        const family = familyCss(span);
        const cs = Number(span.cs) || 0;
        const rise = Number(span.rise) || 0;
        const extra = `${cs ? `letter-spacing:calc(var(--pp) * ${cs}px);` : ''}${rise ? `vertical-align:calc(var(--pp) * ${rise}px);` : ''}`;
        return `<span data-f="${span.f || 0}" data-k="${span.k || 'sans'}" data-lib="${escapeHtml(span.lib || '')}" data-s="${span.s}" data-cs="${cs}" data-rise="${rise}" style="font-size:calc(var(--pp) * ${span.s}px);font-weight:${span.b ? 700 : 400};font-style:${span.i ? 'italic' : 'normal'};color:${span.c};font-family:${escapeHtml(family)};${extra}">${escapeHtml(text)}</span>`;
    }

    function blockHtml(block) {
        let html = '';
        block.lines.forEach((line, i) => {
            const next = block.lines[i + 1];
            line.spans.forEach((span, j) => {
                let text = span.t;
                if (j === line.spans.length - 1 && next && !line.brk) {
                    const trimmed = text.replace(/\s+$/, '');
                    const nextChar = next.spans[0]?.t.trimStart()[0] || '';
                    if (/[­]$/.test(trimmed) || (/-$/.test(trimmed) && /\p{Ll}/u.test(nextChar))) text = trimmed.slice(0, -1);
                    else if (!/\s$/.test(text)) text += ' ';
                }
                html += spanHtml(span, text);
            });
            if (line.brk && next) html += '<br>';
        });
        return html;
    }

    function sampleBackground(page, [x0, y0, x1, y1]) {
        try {
            if (!page.canvas) {
                const canvas = document.createElement('canvas');
                canvas.width = page.img.naturalWidth;
                canvas.height = page.img.naturalHeight;
                canvas.getContext('2d', { willReadFrequently: true }).drawImage(page.img, 0, 0);
                page.canvas = canvas;
            }
            const ctx = page.canvas.getContext('2d', { willReadFrequently: true });
            const sx = page.canvas.width / page.w;
            const sy = page.canvas.height / page.h;
            const points = [[x0 - 2, y0 - 2], [x1 + 2, y0 - 2], [x0 - 2, y1 + 2], [x1 + 2, y1 + 2], [(x0 + x1) / 2, y0 - 2], [(x0 + x1) / 2, y1 + 2], [x0 - 2, (y0 + y1) / 2], [x1 + 2, (y0 + y1) / 2]];
            const samples = points.map(([x, y]) => [...ctx.getImageData(clamp(Math.round(x * sx), 0, page.canvas.width - 1), clamp(Math.round(y * sy), 0, page.canvas.height - 1), 1, 1).data]);
            const median = k => samples.map(p => p[k]).sort((a, b) => a - b)[samples.length >> 1];
            return hex(`rgb(${median(0)},${median(1)},${median(2)})`);
        } catch (err) {
            return '#ffffff';
        }
    }

    function nearestSpan(page, [x, y]) {
        let best = null;
        let score = Infinity;
        (page.data?.blocks || []).forEach(block => {
            const [x0, y0, x1, y1] = block.bbox;
            const d = Math.hypot(Math.max(x0 - x, 0, x - x1), Math.max(y0 - y, 0, y - y1) * 1.5);
            if (d < score) { score = d; best = block; }
        });
        return score < 160 ? best?.lines[0]?.spans[0] || null : null;
    }

    function beginText(page, block, e) {
        finishText(true);
        clearSelection();
        const at = toPt(page, e);
        const inherited = block ? null : nearestSpan(page, at);
        const first = block?.lines[0]?.spans[0] || inherited;
        const size = first?.s || s.opts.textSize;
        const lh = block?.lh || 1.2;
        const bbox = block ? block.bbox.slice() : [at[0], at[1] - size * 0.9, at[0] + size * 6, at[1] + size * 0.3];
        const baseline = block ? block.baseline : at[1];
        const grow = !block || block.lines.every(line => line.brk);
        const wrap = document.createElement('div');
        wrap.className = `pe-text-wrap ${grow ? 'grow' : ''}`;
        const box = document.createElement('div');
        box.className = 'pe-text-box';
        box.contentEditable = 'true';
        box.dataset.family = first ? 'original' : 'sans';
        box.dataset.s = size;
        box.style.fontSize = `calc(var(--pp) * ${size}px)`;
        box.style.lineHeight = lh;
        box.style.textAlign = block?.align || 'left';
        box.style.color = block || (inherited && !s.opts.textColorPicked) ? first.c : s.opts.textColor;
        box.innerHTML = block ? blockHtml(block) : '';
        if (inherited) {
            ensureFont(inherited);
            Object.assign(box.dataset, { f: inherited.f || 0, k: inherited.k || 'sans', lib: inherited.lib || '', cs: inherited.cs || 0, rise: 0 });
            Object.assign(box.style, {
                fontFamily: familyCss(inherited), fontWeight: inherited.b ? 700 : 400, fontStyle: inherited.i ? 'italic' : 'normal',
                letterSpacing: inherited.cs ? `calc(var(--pp) * ${inherited.cs}px)` : ''
            });
        }
        const bg = sampleBackground(page, bbox);
        box.style.background = bg;
        wrap.innerHTML = '<span class="pe-grip" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/></svg></span>';
        wrap.appendChild(box);
        page.layer.appendChild(wrap);
        s.editor = { page, block, wrap, box, bbox, baseline, lh, size, grow, bg, dx: 0, dy: 0, family: box.dataset.family, align: box.style.textAlign };
        placeEditor(s.editor);
        s.editor.initial = JSON.stringify(serialize(s.editor));
        renderContext();
        box.focus({ preventScroll: true });
        placeCaret(box, e);
        box.addEventListener('paste', ev => {
            ev.preventDefault();
            document.execCommand('insertText', false, ev.clipboardData.getData('text/plain'));
        });
        box.addEventListener('beforeinput', ev => {
            if (ev.inputType === 'insertParagraph') {
                ev.preventDefault();
                document.execCommand('insertLineBreak');
            }
        });
        setTimeout(() => s?.editor?.box === box && wrap.scrollIntoView({ block: 'nearest', inline: 'nearest' }), 300);
    }

    function placeCaret(box, e) {
        const sel = window.getSelection();
        let range = null;
        if (document.caretRangeFromPoint) range = document.caretRangeFromPoint(e.clientX, e.clientY);
        else if (document.caretPositionFromPoint) {
            const pos = document.caretPositionFromPoint(e.clientX, e.clientY);
            if (pos) {
                range = document.createRange();
                range.setStart(pos.offsetNode, pos.offset);
            }
        }
        if (!range || !box.contains(range.startContainer)) {
            range = document.createRange();
            range.selectNodeContents(box);
            range.collapse(false);
        }
        sel.removeAllRanges();
        sel.addRange(range);
    }

    function placeEditor(ed) {
        const page = ed.page;
        const [x0, , x1] = ed.bbox;
        const top = ed.baseline - ed.size * (0.9 + (ed.lh - 1.15) / 2) + ed.dy;
        ed.wrap.style.left = `${(x0 + ed.dx) / page.w * 100}%`;
        ed.wrap.style.top = `${top / page.h * 100}%`;
        ed.wrap.style.minWidth = `${(x1 - x0) / page.w * 100}%`;
        if (!ed.grow) ed.wrap.style.width = `${(x1 - x0) / page.w * 100}%`;
    }

    function startTextMove(e) {
        e.preventDefault();
        const ed = s.editor;
        s.drag = { type: 'textmove', page: ed.page, start: toPt(ed.page, e), dx: ed.dx, dy: ed.dy };
    }

    function serialize(ed) {
        const box = ed.box;
        const pp = ed.page.el.clientWidth / ed.page.w;
        const runs = [];
        const add = (text, el) => {
            const cs = getComputedStyle(el);
            const host = el.closest('[data-f]');
            const run = {
                t: text, s: round(parseFloat(cs.fontSize) / pp), c: hex(cs.color),
                b: parseInt(cs.fontWeight, 10) >= 600, i: cs.fontStyle !== 'normal',
                f: host ? Number(host.dataset.f) : 0, k: host?.dataset.k || 'sans',
                cs: Number(host?.dataset.cs) || 0, rise: Number(host?.dataset.rise) || 0, lib: host?.dataset.lib || ''
            };
            const prev = runs[runs.length - 1];
            if (prev && ['s', 'c', 'b', 'i', 'f', 'k', 'cs', 'rise', 'lib'].every(key => prev[key] === run[key])) prev.t += text;
            else runs.push(run);
        };
        const walk = node => node.childNodes.forEach(child => {
            if (child.nodeType === 3) {
                if (child.data) add(child.data.replace(/ /g, ' '), child.parentElement);
            } else if (child.nodeName === 'BR') {
                add('\n', child.parentElement);
            } else if (child.nodeType === 1) {
                if (/^(DIV|P|LI)$/.test(child.nodeName) && runs.length && !runs[runs.length - 1].t.endsWith('\n')) add('\n', box);
                walk(child);
            }
        });
        walk(box);
        const last = runs[runs.length - 1];
        if (last) last.t = last.t.replace(/\n+$/, '');
        return runs.filter(r => r.t);
    }

    function formatBox(command) {
        const ed = s.editor;
        if (!ed) return;
        ed.box.focus({ preventScroll: true });
        document.execCommand('styleWithCSS', false, true);
        const sel = window.getSelection();
        if (sel.isCollapsed || !ed.box.contains(sel.anchorNode)) {
            const range = document.createRange();
            range.selectNodeContents(ed.box);
            sel.removeAllRanges();
            sel.addRange(range);
            command();
            sel.collapseToEnd();
        } else {
            command();
        }
    }

    function pickColor() {
        const ed = s.editor;
        const sel = window.getSelection();
        const range = sel.rangeCount && ed?.box.contains(sel.anchorNode) ? sel.getRangeAt(0).cloneRange() : null;
        new window.EyeDropper().open().then(({ sRGBHex }) => {
            if (s?.editor !== ed) return;
            if (range) {
                sel.removeAllRanges();
                sel.addRange(range);
            }
            formatBox(() => document.execCommand('foreColor', false, sRGBHex));
        }).catch(() => {});
    }

    function resizeBox(delta) {
        const ed = s.editor;
        if (!ed) return;
        [ed.box, ...ed.box.querySelectorAll('[data-s]')].forEach(el => {
            const size = clamp(Number(el.dataset.s) + delta, 4, 200);
            el.dataset.s = size;
            el.style.fontSize = `calc(var(--pp) * ${size}px)`;
        });
        ed.size = clamp(ed.size + delta, 4, 200);
        placeEditor(ed);
    }

    function finishText(save) {
        const ed = s?.editor;
        if (!ed) return;
        if (s.sheet === 'ai') closeSheet();
        const runs = serialize(ed);
        s.editor = null;
        const family = ed.box.dataset.family;
        const align = ed.box.style.textAlign || 'left';
        const changed = editorChanged(ed);
        const empty = !runs.some(r => r.t.trim());
        if (save && changed && !(empty && !ed.block)) {
            const [x0, y0, x1, y1] = ed.bbox;
            const op = {
                type: 'text', page: ed.page.i,
                remove: ed.block ? [...ed.block.lines.flatMap(l => l.rects), ...(ed.block.extra || [])] : [],
                rect: [x0 + ed.dx, y0 + ed.dy, x1 + ed.dx, y1 + ed.dy].map(round),
                baseline: round(ed.baseline + ed.dy), lh: ed.lh, align, family, grow: ed.grow,
                runs: empty ? [] : runs
            };
            ed.box.contentEditable = 'false';
            ed.wrap.classList.add('pending');
            if (empty) ed.wrap.classList.add('empty');
            pushOp(op);
        } else {
            ed.wrap.remove();
        }
        window.getSelection()?.removeAllRanges();
        renderContext();
    }

    function openNote(page, at) {
        closeNote();
        const pop = document.createElement('div');
        pop.className = 'pe-note-pop';
        pop.style.left = `${clamp(at[0] / page.w * 100, 0, 70)}%`;
        pop.style.top = `${at[1] / page.h * 100}%`;
        pop.innerHTML = `
            <textarea rows="3" data-i18n="pe_note_placeholder" placeholder="${escapeHtml(t('pe_note_placeholder'))}"></textarea>
            <div class="pe-note-actions">
                <button type="button" class="btn btn-ghost btn-small" data-note="cancel">${label('pe_cancel')}</button>
                <button type="button" class="btn btn-primary btn-small" data-note="add">${label('pe_note_add')}</button>
            </div>
        `;
        page.layer.appendChild(pop);
        s.note = { page, at, pop };
        pop.addEventListener('click', e => {
            const action = e.target.closest('[data-note]')?.dataset.note;
            if (action === 'add') {
                const text = pop.querySelector('textarea').value.trim();
                if (text) pushOp({ type: 'annot', page: page.i, kind: 'note', rect: [at[0], at[1], at[0] + 20, at[1] + 20], text, color: '#f59e0b' });
                closeNote();
            } else if (action === 'cancel') {
                closeNote();
            }
        });
        pop.querySelector('textarea').focus();
    }

    function closeNote() {
        if (!s?.note) return;
        s.note.pop.remove();
        s.note = null;
    }

    async function onImagePicked() {
        const file = els.imageInput.files[0];
        els.imageInput.value = '';
        const target = s?.imageTarget;
        s && (s.imageTarget = null);
        if (!file || !target) return;
        try {
            const [fileId, size] = await Promise.all([uploadImage(file), imageSize(file)]);
            if (!s) return;
            if (target.replace) {
                const { page, index } = target.replace;
                const image = page.data.images[index];
                const rect = fitInto(image.bbox, size);
                s.reselect = { page: page.i, items: [{ kind: 'image', rect }] };
                clearSelection();
                pushOp({ type: 'image', page: page.i, xref: image.xref, remove: image.bbox, rect, file_id: fileId });
            } else {
                const { page, at } = target;
                const width = Math.min(page.w * 0.4, size[0] * 0.75);
                const height = width * size[1] / size[0];
                const x0 = clamp(at[0] - width / 2, 0, page.w - width);
                const y0 = clamp(at[1] - height / 2, 0, page.h - height);
                const rect = [x0, y0, x0 + width, y0 + height].map(round);
                s.reselect = { page: page.i, items: [{ kind: 'image', rect }] };
                pushOp({ type: 'image', page: page.i, rect, file_id: fileId });
                setTool('edit');
            }
        } catch (err) {
            Toast.error(escapeHtml(err.message || t('err_upload_failed')));
        }
    }

    function fitInto([x0, y0, x1, y1], [w, h]) {
        const scale = Math.min((x1 - x0) / w, (y1 - y0) / h);
        const nw = w * scale;
        const nh = h * scale;
        const cx = (x0 + x1) / 2;
        const cy = (y0 + y1) / 2;
        return [cx - nw / 2, cy - nh / 2, cx + nw / 2, cy + nh / 2].map(round);
    }

    async function uploadImage(file) {
        const form = new FormData();
        form.append('file', file);
        const res = await fetch('/api/upload', { method: 'POST', body: form });
        const body = await res.json().catch(() => ({}));
        if (!body.success) throw new Error(body.error?.message || t('err_upload_failed'));
        PdfDrafts.putImage(body.data.file_id, file);
        return body.data.file_id;
    }

    function imageSize(file) {
        return new Promise((resolve, reject) => {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => { resolve([img.naturalWidth || 1, img.naturalHeight || 1]); URL.revokeObjectURL(url); };
            img.onerror = () => { reject(new Error(t('err_upload_failed'))); URL.revokeObjectURL(url); };
            img.src = url;
        });
    }

    function touchInfo(e) {
        const [a, b] = e.touches;
        return { dist: Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY), x: (a.clientX + b.clientX) / 2, y: (a.clientY + b.clientY) / 2 };
    }

    function onTouchStart(e) {
        if (!s || e.touches.length !== 2) return;
        cancelDrag();
        const info = touchInfo(e);
        s.gesture = { dist: info.dist, zoom: s.zoom, x: info.x, y: info.y };
    }

    function onTouchMove(e) {
        if (!s?.gesture || e.touches.length !== 2) return;
        e.preventDefault();
        const info = touchInfo(e);
        setZoom(s.gesture.zoom * info.dist / s.gesture.dist, info);
        els.scroll.scrollLeft -= info.x - s.gesture.x;
        els.scroll.scrollTop -= info.y - s.gesture.y;
        s.gesture.x = info.x;
        s.gesture.y = info.y;
    }

    function onTouchEnd(e) {
        if (s?.gesture && e.touches.length < 2) setTimeout(() => s && (s.gesture = null), 50);
    }

    function onWheel(e) {
        if (!s || !(e.ctrlKey || e.metaKey)) return;
        e.preventDefault();
        setZoom(s.zoom * Math.exp(-e.deltaY * 0.002), { x: e.clientX, y: e.clientY });
    }

    function onKeyDown(e) {
        if (!s || els.root.classList.contains('hidden')) return;
        const typing = e.target instanceof Element && e.target.closest('input, textarea, select, [contenteditable="true"]');
        const mod = e.ctrlKey || e.metaKey;
        if (e.key === 'Escape') {
            if (s.sheet) closeSheet();
            else if (s.editor) finishText(true);
            else if (s.note) closeNote();
            else if (s.selection) clearSelection();
            else if (s.tool !== 'edit') setTool('edit');
            return;
        }
        if (typing) return;
        const arrows = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
        if (arrows[e.key] && s.selection) {
            e.preventDefault();
            const step = e.shiftKey ? 10 : 1;
            nudge(arrows[e.key][0] * step, arrows[e.key][1] * step);
            return;
        }
        const key = e.key.toLowerCase();
        if (mod && key === 'c' && s.selection) {
            e.preventDefault();
            copySelection();
            return;
        }
        if (mod && key === 'v' && s.clipboard) {
            e.preventDefault();
            paste();
            return;
        }
        if (mod && key === 'd' && s.selection) {
            e.preventDefault();
            duplicateSelection();
            return;
        }
        if (mod && key === 'a' && s.tool === 'edit') {
            e.preventDefault();
            selectAll();
            return;
        }
        if (mod && e.key.toLowerCase() === 'z') {
            e.preventDefault();
            e.shiftKey ? redo() : undo();
        } else if (mod && e.key.toLowerCase() === 'y') {
            e.preventDefault();
            redo();
        } else if ((e.key === 'Delete' || e.key === 'Backspace') && s.selection) {
            e.preventDefault();
            deleteSelection();
        } else if (mod && (e.key === '=' || e.key === '+')) {
            e.preventDefault();
            setZoom(s.zoom * 1.25);
        } else if (mod && e.key === '-') {
            e.preventDefault();
            setZoom(s.zoom / 1.25);
        } else if (mod && e.key === '0') {
            e.preventDefault();
            setZoom(1);
        }
    }

    function committed() {
        if (committedDigest) PdfDrafts.remove(committedDigest);
        committedDigest = null;
    }

    return { open, committed, isOpen: () => !!s };
})();

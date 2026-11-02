const PdfEditor = (() => {
    const TOOLS = ['edit', 'text', 'image', 'markup', 'draw', 'shape', 'note', 'whiteout', 'redact'];
    const ICONS = {
        edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>',
        text: '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
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
        check: '<path d="M5 12l5 5 9-10"/>',
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
    const MIN_ZOOM = 0.4;
    const MAX_ZOOM = 5;

    const $ = id => document.getElementById(id);
    const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
    const round = v => Math.round(v * 100) / 100;
    let els = null;
    let s = null;

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
            context: $('peContext'), tools: $('peTools'), imageInput: $('peImageInput'), notice: $('peNotice')
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
        document.addEventListener('languagechange', () => s && (renderContext(), updateStatus()));
    }

    async function open(file, { onSave, ops } = {}) {
        init();
        s = {
            fileId: file.file_id, ops: Array.isArray(ops) ? ops.slice() : [], redo: [], zoom: 1, tool: 'edit', pages: [], selection: null, editor: null,
            drag: null, gesture: null, reselect: null, imageTarget: null, note: null, fonts: {}, onSave,
            overflowOp: null, dismissed: new WeakSet(),
            opts: { ink: INK[1], mark: MARKS[0], width: WIDTHS[1], markup: 'highlight', shape: 'rect', textColor: INK[0], textSize: 12 }
        };
        els.title.textContent = file.filename;
        els.pages.innerHTML = '';
        els.root.classList.remove('hidden');
        document.body.classList.add('pe-open');
        setTool('edit');
        updateHistory();
        try {
            const { body } = await postJson('/api/pdf/edit/pages', { file_id: s.fileId });
            if (!body.success) throw new Error(errorText(body, 'pdf_err_failed'));
            buildPages(body.data.pages);
        } catch (err) {
            Toast.error(escapeHtml(err.message));
            close(true);
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
        if (!force && (s.ops.length || editorChanged(s.editor)) && !confirm(t('pe_discard_confirm'))) return;
        finishText(false);
        clearTimeout(s.zoomTimer);
        hideNotice();
        s = null;
        els.pages.innerHTML = '';
        els.root.classList.add('hidden');
        document.body.classList.remove('pe-open');
    }

    function save() {
        if (!s) return;
        finishText(true);
        const ops = s.ops.slice();
        const onSave = s.onSave;
        if (!ops.length) return close(true);
        close(true);
        onSave?.(ops);
    }

    function buildPages(sizes) {
        s.pages = sizes.map(([w, h], i) => {
            const el = document.createElement('div');
            el.className = 'pe-page';
            el.dataset.page = i;
            el.innerHTML = `<img class="pe-img" alt=""><div class="pe-layer"></div><svg class="pe-live" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"></svg><span class="pe-spinner"></span>`;
            els.pages.appendChild(el);
            return { i, w, h, el, img: el.querySelector('.pe-img'), layer: el.querySelector('.pe-layer'), svg: el.querySelector('.pe-live'), data: null, rev: 0, loadedRev: -1, loadedWidth: 0, token: 0, visible: false };
        });
        layoutPages();
        requestAnimationFrame(onScroll);
    }

    function onScroll() {
        if (!s || !s.pages.length) return;
        const view = els.scroll.getBoundingClientRect();
        let current = 0;
        s.pages.forEach(page => {
            const r = page.el.getBoundingClientRect();
            if (r.top <= view.top + view.height / 2) current = page.i;
            page.visible = r.bottom > view.top - 800 && r.top < view.bottom + 800;
            if (page.visible) ensure(page);
            else if ((r.bottom < view.top - 3000 || r.top > view.bottom + 3000) && page.img.hasAttribute('src') && s.editor?.page !== page) unload(page);
        });
        els.pill.textContent = `${current + 1} / ${s.pages.length}`;
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
        Object.keys(data.overflow || {}).forEach(i => {
            const op = sent[Number(i)];
            if (op && !op.fit && !s.dismissed.has(op) && s.ops.includes(op)) showNotice(op);
        });
    }

    function showNotice(op) {
        s.overflowOp = op;
        els.notice.classList.remove('hidden');
    }

    function hideNotice() {
        if (s) s.overflowOp = null;
        els.notice.classList.add('hidden');
    }

    function onNoticeClick(e) {
        const action = e.target.closest('[data-notice]')?.dataset.notice;
        const op = s?.overflowOp;
        if (!action || !op) return;
        if (action === 'fit') {
            op.fit = true;
            touch(op.page);
        } else {
            s.dismissed.add(op);
        }
        hideNotice();
    }

    function opsFor(index) {
        return s.ops.filter(op => op.page === index);
    }

    function touch(index) {
        const page = s.pages[index];
        if (!page) return;
        page.rev++;
        page.el.classList.add('stale');
        if (page.visible) ensure(page);
    }

    function pushOp(op) {
        s.ops.push(op);
        s.redo = [];
        touch(op.page);
        updateHistory();
    }

    function undo() {
        if (!s) return;
        finishText(false);
        const op = s.ops.pop();
        if (!op) return;
        s.redo.push(op);
        clearSelection();
        touch(op.page);
        updateHistory();
    }

    function redo() {
        if (!s) return;
        finishText(false);
        const op = s.redo.pop();
        if (!op) return;
        s.ops.push(op);
        clearSelection();
        touch(op.page);
        updateHistory();
    }

    function updateHistory() {
        if (s.overflowOp && !s.ops.includes(s.overflowOp)) hideNotice();
        els.undo.disabled = !s.ops.length;
        els.redo.disabled = !s.redo.length;
        updateStatus();
    }

    function updateStatus() {
        if (s.ops.length) i18n.set(els.status, 'pe_changes', { count: s.ops.length });
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
        if (s.reselect?.page === page.i) {
            const target = s.reselect;
            s.reselect = null;
            const list = target.kind === 'image' ? data.images.map(x => x.bbox) : data.annots.map(x => x.rect);
            const index = list.findIndex(r => r.every((v, k) => Math.abs(v - target.rect[k]) < 3));
            if (index >= 0) select(page, target.kind, index);
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
                ${chip('delete-text', icon('trash'), { title: 'pe_delete' })}
            `;
        } else if (s.selection) {
            const sel = s.selection;
            if (sel.kind === 'image') {
                html = `${chip('replace-image', icon('replace') + label('pe_replace'))}${chip('delete-object', icon('trash') + label('pe_delete'))}`;
            } else {
                const annot = sel.page.data.annots[sel.index];
                const text = annot.text ? `<p class="pe-note-text">${escapeHtml(annot.text)}</p>` : '';
                html = `${text}${chip('delete-object', icon('trash') + label('pe_delete'))}`;
            }
        } else if (s.tool === 'markup') {
            html = MARKUP_KINDS.map(k => chip('markup', label(`pe_markup_${k}`), { value: k, active: o.markup === k })).join('') + swatches('mark', MARKS, o.mark);
        } else if (s.tool === 'draw') {
            html = swatches('ink', INK, o.ink) + widths(o.width);
        } else if (s.tool === 'shape') {
            html = SHAPES.map(k => chip('shape', label(`pe_shape_${k}`), { value: k, active: o.shape === k })).join('') + swatches('ink', INK, o.ink) + widths(o.width);
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
            case 'replace-image':
                s.imageTarget = { replace: s.selection };
                els.imageInput.click();
                return;
            case 'delete-object': deleteSelection(); return;
        }
        renderContext();
    }

    function select(page, kind, index) {
        clearSelection();
        const el = page.layer.querySelector(kind === 'image' ? `[data-img="${index}"]` : `[data-an="${index}"]`);
        if (!el) return;
        el.classList.add('selected');
        if (kind === 'image' && page.data.images[index].movable !== false) el.insertAdjacentHTML('beforeend', '<span class="pe-handle"></span>');
        s.selection = { page, kind, index, el };
        renderContext();
    }

    function clearSelection() {
        if (!s?.selection) return;
        const el = s.selection.el;
        el.classList.remove('selected');
        el.querySelector('.pe-handle')?.remove();
        s.selection = null;
        renderContext();
    }

    function deleteSelection() {
        const sel = s.selection;
        if (!sel) return;
        clearSelection();
        if (sel.kind === 'image') {
            const image = sel.page.data.images[sel.index];
            pushOp({ type: 'image', page: sel.page.i, xref: image.xref, remove: image.bbox });
        } else {
            pushOp({ type: 'annot_edit', page: sel.page.i, target: sel.page.data.annots[sel.index].rect, delete: true });
        }
    }

    function onClick(e) {
        if (!s || s.tool !== 'edit' || s.gesture) return;
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
            if (!obj) return clearSelection();
            const kind = obj.classList.contains('pe-image') ? 'image' : 'annot';
            const index = Number(kind === 'image' ? obj.dataset.img : obj.dataset.an);
            if (s.selection?.el !== obj) select(page, kind, index);
            const movable = kind === 'image' ? page.data.images[index].movable !== false : page.data.annots[index].movable;
            if (!movable) return;
            const rect = (kind === 'image' ? page.data.images[index].bbox : page.data.annots[index].rect).slice();
            s.drag = { type: e.target.closest('.pe-handle') ? 'resize' : 'move', page, el: obj, kind, index, start: p, origin: rect, rect, moved: false };
            e.preventDefault();
            return;
        }
        e.preventDefault();
        if (s.tool === 'text') return beginText(page, null, e);
        if (s.tool === 'image') {
            s.imageTarget = { page, at: p };
            els.imageInput.click();
            return;
        }
        if (s.tool === 'note') return openNote(page, p);
        const ns = 'http://www.w3.org/2000/svg';
        const shape = document.createElementNS(ns, s.tool === 'draw' ? 'polyline' : 'g');
        page.svg.appendChild(shape);
        s.drag = { type: s.tool, page, start: p, end: p, points: [p], el: shape, word: s.tool === 'markup' ? nearestWord(page, p) : -1 };
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
            const [x0, y0, x1, y1] = d.origin;
            if (d.type === 'move') d.rect = [x0 + dx, y0 + dy, x1 + dx, y1 + dy];
            else {
                const w = Math.max(8, x1 - x0 + dx);
                d.rect = [x0, y0, x0 + w, y0 + w * (y1 - y0) / (x1 - x0)];
            }
            d.el.setAttribute('style', pct(d.page, d.rect));
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
            if (!d.moved) return;
            const rect = d.rect.map(round);
            s.reselect = { page: page.i, kind: d.kind, rect };
            if (d.kind === 'image') pushOp({ type: 'image', page: page.i, xref: page.data.images[d.index].xref, remove: d.origin, rect });
            else pushOp({ type: 'annot_edit', page: page.i, target: d.origin, rect });
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
        } else {
            d.el.remove();
        }
    }

    function cancelDrag() {
        if (!s?.drag) return;
        if (s.drag.el && s.drag.el.ownerSVGElement) s.drag.el.remove();
        if (s.drag.type === 'move' || s.drag.type === 'resize') s.drag.el.setAttribute('style', pct(s.drag.page, s.drag.origin));
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
            const fill = d.type === 'redact' ? '#000' : '#fff';
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
        return `<span data-f="${span.f || 0}" data-k="${span.k || 'sans'}" data-s="${span.s}" data-cs="${cs}" data-rise="${rise}" style="font-size:calc(var(--pp) * ${span.s}px);font-weight:${span.b ? 700 : 400};font-style:${span.i ? 'italic' : 'normal'};color:${span.c};font-family:${escapeHtml(family)};${extra}">${escapeHtml(text)}</span>`;
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
            Object.assign(box.dataset, { f: inherited.f || 0, k: inherited.k || 'sans', cs: inherited.cs || 0, rise: 0 });
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
                cs: Number(host?.dataset.cs) || 0, rise: Number(host?.dataset.rise) || 0
            };
            const prev = runs[runs.length - 1];
            if (prev && ['s', 'c', 'b', 'i', 'f', 'k', 'cs', 'rise'].every(key => prev[key] === run[key])) prev.t += text;
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
                s.reselect = { page: page.i, kind: 'image', rect };
                clearSelection();
                pushOp({ type: 'image', page: page.i, xref: image.xref, remove: image.bbox, rect, file_id: fileId });
            } else {
                const { page, at } = target;
                const width = Math.min(page.w * 0.4, size[0] * 0.75);
                const height = width * size[1] / size[0];
                const x0 = clamp(at[0] - width / 2, 0, page.w - width);
                const y0 = clamp(at[1] - height / 2, 0, page.h - height);
                const rect = [x0, y0, x0 + width, y0 + height].map(round);
                s.reselect = { page: page.i, kind: 'image', rect };
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
            if (s.editor) finishText(true);
            else if (s.note) closeNote();
            else if (s.selection) clearSelection();
            else if (s.tool !== 'edit') setTool('edit');
            return;
        }
        if (typing) return;
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

    return { open, isOpen: () => !!s };
})();

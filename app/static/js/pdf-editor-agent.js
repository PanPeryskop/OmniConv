const PdfAgent = (() => {
    const bridge = PdfEditor.bridge;
    const API = '/api/pdf/edit/agent';
    const STORE = 'pe-agent:';
    const SCOPES = ['page', 'pages', 'document', 'selection'];
    const SUGGESTIONS = [
        { key: 'typos', scope: 'page', send: true },
        { key: 'translate', scope: 'document', send: false },
        { key: 'redact', scope: 'document', send: true },
        { key: 'summary', scope: 'document', send: true }
    ];
    const KIND_ICONS = { text: 'edit', style: 'bold', insert: 'text', delete: 'trash', annot: 'markup', redact: 'redact', page: 'rotate' };
    const PROVIDERS = { lmstudio: 'LM Studio', fake: 'Fake LM' };
    const GLYPHS = {
        send: '<path d="M5 12h13M13 6l6 6-6 6"/>',
        stop: '<rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor"/>',
        chat: '<path d="M4 5h16v11H9l-5 4z"/><path d="M12 8v5M9.5 10.5h5"/>',
        eye: '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
        down: '<path d="M12 5v14M6 13l6 6 6-6"/>',
        minus: '<path d="M6 12h12"/>'
    };
    const STICK_PX = 48;
    const DIFF_LIMIT = 250000;
    const FLASH_MS = 1600;
    const SAVE_MS = 250;
    const INPUT_MAX = 160;

    const esc = value => bridge.escapeHtml(value);
    const tr = (key, vars) => bridge.t(key, vars);
    let el = null;
    let chat = null;
    let status = null;
    let stream = null;
    let applied = new Set();
    let pageCache = new Map();
    let chainCache = new Map();
    let stick = true;
    let hovered = null;
    let flashTimer = 0;
    let saveTimer = 0;
    let frame = 0;
    let dirty = new Set();
    let opening = false;

    function glyph(name) {
        return `<svg viewBox="0 0 24 24" aria-hidden="true">${GLYPHS[name]}</svg>`;
    }

    function storage() {
        try {
            return window.sessionStorage;
        } catch (err) {
            return null;
        }
    }

    function freshChat(session) {
        return {
            digest: session.digest, fileId: session.fileId, sessionId: null, items: [], proposals: {},
            scope: { kind: 'page', pages: '' }, selection: null, turn: 0, seq: 0, n: 0, draft: ''
        };
    }

    function load(session) {
        try {
            const raw = storage()?.getItem(STORE + session.digest);
            const saved = raw ? JSON.parse(raw) : null;
            if (!saved || !Array.isArray(saved.items)) return freshChat(session);
            const items = saved.items.map(item => (item.type === 'tool' && ['start', 'progress'].includes(item.status) ? { ...item, status: 'stopped' } : { ...item, streaming: false }));
            return { ...freshChat(session), ...saved, items, fileId: session.fileId, digest: session.digest };
        } catch (err) {
            return freshChat(session);
        }
    }

    function persist() {
        clearTimeout(saveTimer);
        saveTimer = 0;
        if (!chat) return;
        try {
            const items = chat.items.map(item => (item.streaming ? { ...item, streaming: false } : item));
            storage()?.setItem(STORE + chat.digest, JSON.stringify({ ...chat, items, draft: el?.input.value ?? chat.draft }));
        } catch (err) {
            return;
        }
    }

    function save() {
        clearTimeout(saveTimer);
        saveTimer = setTimeout(persist, SAVE_MS);
    }

    function forget(digest) {
        try {
            storage()?.removeItem(STORE + digest);
        } catch (err) {
            return;
        }
    }

    function errorText(code, message) {
        const text = code ? tr(code) : '';
        return text && text !== code ? text : message || tr('pa_err_generic');
    }

    function inline(text) {
        return esc(text).split(/(`[^`\n]+`)/).map((part, i) => (i % 2 ? `<code>${part.slice(1, -1)}</code>` : part.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>'))).join('');
    }

    function markdown(text) {
        const blocks = [];
        let para = [];
        let list = null;
        const flush = () => {
            if (para.length) blocks.push(`<p>${para.map(inline).join('<br>')}</p>`);
            para = [];
        };
        const end = () => {
            if (list) blocks.push(`<${list.tag}>${list.items.map(item => `<li>${inline(item)}</li>`).join('')}</${list.tag}>`);
            list = null;
        };
        String(text || '').split('\n').forEach(line => {
            const m = line.match(/^\s*(?:([-*•])|(\d+)[.)])\s+(.*)$/);
            if (m) {
                flush();
                const tag = m[1] ? 'ul' : 'ol';
                if (list?.tag !== tag) {
                    end();
                    list = { tag, items: [] };
                }
                list.items.push(m[3]);
            } else if (!line.trim()) {
                flush();
                end();
            } else {
                end();
                para.push(line);
            }
        });
        flush();
        end();
        return blocks.join('');
    }

    function tokens(text) {
        return String(text || '').match(/\s+|[^\s]+/g) || [];
    }

    function diff(before, after) {
        const a = tokens(before);
        const b = tokens(after);
        if (a.length * b.length > DIFF_LIMIT) return [['del', String(before)], ['ins', String(after)]];
        const n = a.length;
        const m = b.length;
        const dp = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
        for (let i = n - 1; i >= 0; i--) {
            for (let j = m - 1; j >= 0; j--) dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
        const raw = [];
        let i = 0;
        let j = 0;
        while (i < n || j < m) {
            if (i < n && j < m && a[i] === b[j]) {
                raw.push(['eq', a[i]]);
                i++;
                j++;
            }
            else if (j >= m || (i < n && dp[i + 1][j] >= dp[i][j + 1])) raw.push(['del', a[i++]]);
            else raw.push(['ins', b[j++]]);
        }
        const parts = [];
        let del = '';
        let ins = '';
        const flush = () => {
            if (del) parts.push(['del', del]);
            if (ins) parts.push(['ins', ins]);
            del = '';
            ins = '';
        };
        raw.forEach(([type, text], k) => {
            const between = type === 'eq' && !text.trim() && (del || ins) && raw[k + 1] && raw[k + 1][0] !== 'eq';
            if (type === 'del' || between) del += text;
            if (type === 'ins' || between) ins += text;
            if (type === 'eq' && !between) {
                flush();
                const last = parts[parts.length - 1];
                if (last?.[0] === 'eq') last[1] += text;
                else parts.push(['eq', text]);
            }
        });
        flush();
        return parts;
    }

    function diffHtml(p) {
        if (p.kind === 'redact') return p.before ? `<span class="pa-redacted">${esc(p.before)}</span>` : '';
        if (p.before && p.after) return diff(p.before, p.after).map(([type, text]) => (type === 'eq' ? esc(text) : `<${type}>${esc(text)}</${type}>`)).join('');
        if (p.before) return `<del>${esc(p.before)}</del>`;
        if (p.after) return `<ins>${esc(p.after)}</ins>`;
        return '';
    }

    function pageOps(page) {
        if (!pageCache.has(page)) pageCache.set(page, bridge.opsForPage(page));
        return pageCache.get(page);
    }

    function proposals() {
        return Object.values(chat?.proposals || {}).sort((a, b) => a.seq - b.seq);
    }

    function chainOf(p) {
        if (chainCache.has(p.id)) return chainCache.get(p.id);
        const all = proposals();
        const chain = new Set([p.id]);
        const queue = [p];
        while (queue.length) {
            const current = queue.shift();
            all.forEach(q => {
                if (chain.has(q.id)) return;
                if (current.depends_on.includes(q.id) || q.depends_on.includes(current.id)) {
                    chain.add(q.id);
                    queue.push(q);
                }
            });
        }
        chain.forEach(id => chainCache.set(id, chain));
        return chain;
    }

    function fresh(p, before = []) {
        const session = bridge.session();
        if (!session || !p.ops.length || !session.order.includes(p.page)) return false;
        const chain = chainOf(p);
        if (before.some(q => q.page === p.page && !chain.has(q.id))) return false;
        if (!p.base || typeof p.base.count !== 'number') return true;
        const ops = pageOps(p.page).filter(op => !chain.has(op.proposal));
        const last = ops.length ? ops[ops.length - 1].g ?? null : null;
        return ops.length === p.base.count && last === (p.base.last_g ?? null);
    }

    function stateOf(p) {
        if (applied.has(p.id)) return 'applied';
        if (p.rejected) return 'rejected';
        return fresh(p) ? 'pending' : 'stale';
    }

    function dependencies(p, seen = new Set()) {
        p.depends_on.forEach(id => {
            const q = chat.proposals[id];
            if (!q || seen.has(q)) return;
            seen.add(q);
            dependencies(q, seen);
        });
        return seen;
    }

    function dependents(p) {
        const found = new Set();
        let grew = true;
        while (grew) {
            grew = false;
            proposals().forEach(q => {
                if (found.has(q) || q === p) return;
                if (q.depends_on.some(id => id === p.id || [...found].some(f => f.id === id))) {
                    found.add(q);
                    grew = true;
                }
            });
        }
        return [...found].sort((a, b) => a.seq - b.seq);
    }

    function openDependencies(p) {
        return [...dependencies(p)].filter(q => !applied.has(q.id) && !q.rejected).sort((a, b) => a.seq - b.seq);
    }

    function openDependents(p) {
        return dependents(p).filter(q => !applied.has(q.id) && !q.rejected);
    }

    function pageNumber(page) {
        const order = bridge.session()?.order || [];
        const position = order.indexOf(page);
        return position < 0 ? null : position + 1;
    }

    function feedback(id, decision) {
        if (!chat?.sessionId) return;
        bridge.postJson(`${API}/sessions/${encodeURIComponent(chat.sessionId)}/feedback`, { proposal_id: id, decision }).catch(() => null);
    }

    function apply(list, label) {
        const batch = new Set();
        list.forEach(p => {
            openDependencies(p).forEach(q => batch.add(q));
            if (!applied.has(p.id) && !p.rejected) batch.add(p);
        });
        const ordered = [...batch].sort((a, b) => a.seq - b.seq);
        const ready = [];
        ordered.forEach(q => {
            if (fresh(q, ready)) ready.push(q);
        });
        if (!ready.length || (list.length === 1 && ready.length !== ordered.length)) return refreshProposals();
        const ops = ready.flatMap(q => q.ops.map(op => ({ ...op, proposal: q.id })));
        bridge.apply(ops, { label });
        ready.forEach(q => feedback(q.id, 'accepted'));
        flash(ready);
        save();
    }

    function reject(p) {
        const doomed = openDependents(p);
        [p, ...doomed].forEach(q => {
            q.rejected = true;
            q.by = q === p ? null : p.id;
            feedback(q.id, 'rejected');
        });
        if (hovered && [p, ...doomed].some(q => q.id === hovered)) unhover();
        refreshProposals();
        save();
    }

    function flash(list) {
        const last = list[list.length - 1];
        const rects = list.filter(q => q.page === last.page).flatMap(q => q.rects);
        clearTimeout(flashTimer);
        hovered = null;
        bridge.focus(last.page, rects, 'applied');
        flashTimer = setTimeout(() => {
            flashTimer = 0;
            if (!hovered) bridge.clearFocus();
        }, FLASH_MS);
    }

    function show(p) {
        if (bridge.compact()) bridge.side(false);
        clearTimeout(flashTimer);
        bridge.focus(p.page, p.rects, stateOf(p) === 'applied' ? 'applied' : 'proposal');
    }

    function hover(p) {
        if (hovered === p.id) return;
        hovered = p.id;
        clearTimeout(flashTimer);
        bridge.focus(p.page, p.rects, stateOf(p) === 'applied' ? 'applied' : stateOf(p) === 'stale' ? 'error' : 'proposal');
    }

    function unhover() {
        if (!hovered) return;
        hovered = null;
        bridge.clearFocus();
    }

    function providerName() {
        return PROVIDERS[status?.provider] || status?.provider || '';
    }

    function ready() {
        return status?.status === 'ok';
    }

    function modelLine() {
        if (!status || status === 'loading') return '<span class="pa-skeleton pa-skeleton-line" aria-hidden="true"></span>';
        const ok = status.status === 'ok';
        const text = ok ? [providerName(), status.model].filter(Boolean).join(' · ') : tr('pa_offline');
        return `<span class="pa-dot ${ok ? 'ok' : 'off'}" aria-hidden="true"></span><span class="pa-model-text">${esc(text)}</span>`;
    }

    function noticeHtml() {
        if (!status || status === 'loading') return '';
        if (status.status !== 'ok') {
            const reason = status.status === 'unavailable' ? tr('pa_status_unavailable') : errorText(`err_ai_${status.status}`, tr('pa_status_unavailable'));
            return `<div class="pa-notice off" role="status">${bridge.icon('warning')}<span>${esc(reason)}</span>
                <button type="button" class="pa-link" data-pa="retry">${esc(tr('pa_retry'))}</button></div>`;
        }
        return '';
    }

    function scopeLabel(kind) {
        return tr(`pa_scope_${kind}`);
    }

    function currentSelection() {
        return bridge.selection() || chat.selection;
    }

    function scopeNote() {
        const kind = chat.scope.kind;
        const session = bridge.session();
        if (kind === 'page' && session) return esc(tr('pa_scope_page_note', { page: pageNumber(session.current) ?? 1, total: session.order.length }));
        if (kind === 'document' && session) return esc(tr('pa_scope_document_note', { count: session.order.length }));
        if (kind === 'selection') {
            const sel = currentSelection();
            if (!sel) return `<span class="pa-warn">${esc(tr('pa_selection_none'))}</span>`;
            const text = sel.text.length > 80 ? `${sel.text.slice(0, 80)}…` : sel.text;
            return esc(tr('pa_selection_text', { text }));
        }
        return '';
    }

    function emptyHtml() {
        const disabled = ready() ? '' : 'disabled';
        return `<div class="pa-empty">
            <span class="pa-empty-mark">${bridge.icon('sparkles')}</span>
            <p class="pa-empty-title">${esc(tr('pa_empty_title'))}</p>
            <p class="pa-empty-text">${esc(tr('pa_empty_text'))}</p>
            <div class="pa-suggestions">${SUGGESTIONS.map(s => `<button type="button" class="pa-suggestion" data-pa="suggest" data-key="${s.key}" ${disabled}>${esc(tr(`pa_s_${s.key}`))}</button>`).join('')}</div>
        </div>`;
    }

    function toolLabel(name) {
        const key = `pa_tool_${name}`;
        const text = tr(key);
        return text === key ? name : text;
    }

    function titleOf(p) {
        const key = `pa_title_${p.kind}`;
        const text = tr(key);
        return text === key ? p.title : text;
    }

    function cardHtml(p) {
        const state = stateOf(p);
        const number = pageNumber(p.page);
        const deps = state === 'pending' ? openDependencies(p) : [];
        const after = state === 'pending' ? openDependents(p) : [];
        const by = p.by && chat.proposals[p.by];
        const kindIcon = KIND_ICONS[p.kind] || 'edit';
        const body = diffHtml(p);
        let foot = '';
        if (state === 'pending') {
            const rejectTitle = after.length ? tr('pa_rejects_with', { count: after.length }) : tr('pa_reject');
            foot = `<button type="button" class="pa-btn ghost" data-pa="show" data-id="${esc(p.id)}">${glyph('eye')}<span>${esc(tr('pa_show'))}</span></button>
                <button type="button" class="pa-btn" data-pa="reject" data-id="${esc(p.id)}" title="${esc(rejectTitle)}" aria-label="${esc(`${tr('pa_reject')}: ${titleOf(p)}`)}">${bridge.icon('cross')}<span>${esc(tr('pa_reject'))}</span></button>
                <button type="button" class="pa-btn primary" data-pa="apply" data-id="${esc(p.id)}" aria-label="${esc(`${tr('pa_apply')}: ${titleOf(p)}`)}">${bridge.icon('check')}<span>${esc(tr('pa_apply'))}</span></button>`;
        } else {
            const text = state === 'applied' ? tr('pa_applied') : state === 'stale' ? tr('pa_stale') : by ? tr('pa_rejected_with', { title: titleOf(by) }) : tr('pa_rejected');
            const extra = state === 'stale' ? `<button type="button" class="pa-btn ghost" data-pa="reject" data-id="${esc(p.id)}">${esc(tr('pa_dismiss'))}</button>` : '';
            foot = `<span class="pa-state">${state === 'applied' ? bridge.icon('check') : state === 'stale' ? bridge.icon('warning') : ''}<span>${esc(text)}</span></span>
                <button type="button" class="pa-btn ghost" data-pa="show" data-id="${esc(p.id)}">${glyph('eye')}<span>${esc(tr('pa_show'))}</span></button>${extra}`;
        }
        return `<article class="pa-card is-${state}" data-key="p:${esc(p.id)}" data-id="${esc(p.id)}" aria-label="${esc(titleOf(p))}">
            <header class="pa-card-head">
                <span class="pa-kind" title="${esc(tr(`pa_kind_${p.kind}`))}">${bridge.icon(kindIcon)}</span>
                <h3 class="pa-card-title" title="${esc(p.title)}">${esc(titleOf(p))}</h3>
                ${number ? `<span class="pa-page">${esc(tr('pe_page_short', { page: number }))}</span>` : ''}
            </header>
            ${p.reason ? `<p class="pa-reason">${esc(p.reason)}</p>` : ''}
            ${body ? `<div class="pa-diff">${body}</div>` : ''}
            ${termsHtml(p)}
            ${deps.length ? `<p class="pa-deps">${esc(tr('pa_applies_with', { count: deps.length }))}</p>` : ''}
            <div class="pa-card-foot">${foot}</div>
        </article>`;
    }

    function itemHtml(item) {
        const key = `data-key="${esc(item.key)}"`;
        if (item.type === 'user') {
            return `<div class="pa-msg user" ${key}><span class="pa-sr">${esc(tr('pa_you'))}:</span><div class="pa-bubble">${esc(item.text)}</div>
                <span class="pa-tag">${esc(scopeLabel(item.scope))}</span></div>`;
        }
        if (item.type === 'assistant') {
            return `<div class="pa-msg assistant${item.streaming ? ' streaming' : ''}" ${key} aria-busy="${item.streaming ? 'true' : 'false'}"><span class="pa-sr">${esc(tr('pe_agent'))}:</span><div class="pa-bubble pa-md">${markdown(item.text)}</div></div>`;
        }
        if (item.type === 'tool') {
            const mark = item.status === 'done' ? bridge.icon('check') : item.status === 'error' ? bridge.icon('cross') : item.status === 'stopped' ? glyph('minus') : '<span class="pa-spin" aria-hidden="true"></span>';
            const progress = item.status === 'progress' && item.total > 0;
            const count = progress ? `<span class="pa-tool-count">${esc(tr('pa_tool_progress', { done: item.done, total: item.total }))}</span>` : '';
            const summary = item.summary ? `<span class="pa-tool-sum">${esc(item.summary)}</span>` : '';
            const bar = progress ? `<span class="pa-tool-bar" style="width:${Math.round(Math.min(1, item.done / item.total) * 100)}%"></span>` : '';
            const state = ['start', 'progress'].includes(item.status) ? 'running' : esc(item.status);
            return `<div class="pa-tool ${state}" ${key} title="${esc(item.summary || item.name)}"><span class="pa-tool-mark">${mark}</span><span class="pa-tool-name">${esc(toolLabel(item.name))}</span>${count}${summary}${bar}</div>`;
        }
        if (item.type === 'proposal') {
            const p = chat.proposals[item.id];
            return p ? cardHtml(p) : '';
        }
        if (item.type === 'error') {
            return `<div class="pa-error" ${key} role="alert">${bridge.icon('warning')}<span>${esc(errorText(item.code, item.message))}</span></div>`;
        }
        return `<p class="pa-note" ${key}>${esc(tr(item.textKey))}</p>`;
    }

    function typingHtml() {
        return `<div class="pa-typing" data-key="typing" role="status"><span class="pa-sr">${esc(tr('pa_thinking'))}</span><span class="pa-skeleton"></span><span class="pa-skeleton short"></span></div>`;
    }

    function bulkCount() {
        return proposals().filter(p => stateOf(p) === 'pending').length;
    }

    function panelHtml() {
        const options = SCOPES.map(kind => `<option value="${kind}" ${chat.scope.kind === kind ? 'selected' : ''}>${esc(scopeLabel(kind))}</option>`).join('');
        return `<div class="pa" data-pa-root>
            <div class="pa-grab" data-pa-grab><span class="pa-grabber"></span></div>
            <header class="pa-head" data-pa-grab>
                <span class="pa-mark">${bridge.icon('sparkles')}</span>
                <div class="pa-heading">
                    <h2 class="pa-title" id="paTitle" tabindex="-1">${esc(tr('pe_agent'))}</h2>
                    <p class="pa-model" data-pa-model>${modelLine()}</p>
                </div>
                <button type="button" class="pe-icon-btn" data-pa="new" title="${esc(tr('pa_new_chat'))}" aria-label="${esc(tr('pa_new_chat'))}">${glyph('chat')}</button>
                <button type="button" class="pe-icon-btn" data-pa="close" title="${esc(tr('close'))}" aria-label="${esc(tr('close'))}">${bridge.icon('close')}</button>
            </header>
            <div class="pa-scope">
                <label class="pa-scope-label" for="paScope">${esc(tr('pa_scope'))}</label>
                <select class="pe-select pa-select" id="paScope" aria-label="${esc(tr('pa_scope'))}">${options}</select>
                <input type="text" class="pa-pages" data-pa-pages value="${esc(chat.scope.pages)}" placeholder="${esc(tr('pa_pages_placeholder'))}" aria-label="${esc(tr('pa_pages_label'))}" autocomplete="off" ${chat.scope.kind === 'pages' ? '' : 'hidden'}>
            </div>
            <p class="pa-scope-note" data-pa-note>${scopeNote()}</p>
            <div data-pa-notice>${noticeHtml()}</div>
            <div class="pa-body">
                <div class="pa-log" data-pa-log role="log" aria-live="polite" aria-relevant="additions" aria-labelledby="paTitle" tabindex="0"></div>
                <button type="button" class="pa-jump" data-pa="jump" hidden title="${esc(tr('pa_jump'))}" aria-label="${esc(tr('pa_jump'))}">${glyph('down')}</button>
            </div>
            <div class="pa-bulk" data-pa-bulk hidden></div>
            <form class="pa-compose" data-pa-compose>
                <textarea class="pa-input" rows="1" enterkeyhint="send" placeholder="${esc(tr('pa_input'))}" aria-label="${esc(tr('pa_input'))}"></textarea>
                <button type="submit" class="pa-send" data-pa-send></button>
            </form>
            <p class="pa-hint">${esc(tr('pa_hint'))}</p>
        </div>`;
    }

    function render() {
        const slot = bridge.sheetSlot();
        if (!chat || !slot) return;
        const draft = el?.input.value ?? chat.draft ?? '';
        slot.innerHTML = panelHtml();
        const root = slot.querySelector('[data-pa-root]');
        el = {
            slot, root, digest: chat.digest, log: root.querySelector('[data-pa-log]'), input: root.querySelector('.pa-input'),
            send: root.querySelector('[data-pa-send]'), bulk: root.querySelector('[data-pa-bulk]'), note: root.querySelector('[data-pa-note]'),
            notice: root.querySelector('[data-pa-notice]'), model: root.querySelector('[data-pa-model]'), scope: root.querySelector('#paScope'),
            pages: root.querySelector('[data-pa-pages]'), jump: root.querySelector('[data-pa="jump"]'), form: root.querySelector('[data-pa-compose]')
        };
        el.input.value = draft;
        bind(root);
        renderLog();
        renderCompose();
        renderBulk();
        autosize();
        stick = true;
        scrollEnd(true);
    }

    function bind(root) {
        root.addEventListener('click', onClick);
        root.addEventListener('keydown', onKeyDown);
        root.addEventListener('focusin', () => el && (el.note.innerHTML = scopeNote()));
        root.addEventListener('pointerdown', onGrab);
        el.form.addEventListener('submit', e => {
            e.preventDefault();
            stream ? stop() : send(el.input.value);
        });
        el.input.addEventListener('input', () => {
            autosize();
            chat.draft = el.input.value;
            save();
        });
        el.scope.addEventListener('change', () => setScope(el.scope.value));
        el.pages.addEventListener('input', () => {
            chat.scope.pages = el.pages.value;
            save();
        });
        el.log.addEventListener('scroll', onScroll, { passive: true });
        el.log.addEventListener('pointerover', onPointerOver);
        el.log.addEventListener('pointerout', onPointerOut);
        el.log.addEventListener('focusin', onCardFocus);
    }

    function renderLog() {
        if (!el) return;
        el.log.innerHTML = chat.items.length ? chat.items.map(itemHtml).join('') + (stream ? typingHtml() : '') : emptyHtml();
        if (chat.items.length) syncTyping();
    }

    function renderHeader() {
        if (!el) return;
        el.model.innerHTML = modelLine();
        el.notice.innerHTML = noticeHtml();
        if (!chat.items.length) renderLog();
        renderCompose();
    }

    function renderCompose() {
        if (!el) return;
        const busy = !!stream;
        el.send.classList.toggle('stop', busy);
        el.send.innerHTML = busy ? glyph('stop') : glyph('send');
        el.send.setAttribute('aria-label', tr(busy ? 'pa_stop' : 'pa_send'));
        el.send.title = tr(busy ? 'pa_stop' : 'pa_send');
        el.send.disabled = !busy && !ready();
        el.input.disabled = busy;
        el.root.classList.toggle('busy', busy);
    }

    function renderBulk() {
        if (!el) return;
        const count = bulkCount();
        el.bulk.hidden = count < 2;
        el.bulk.innerHTML = count < 2 ? '' : `<span class="pa-bulk-text">${esc(tr('pa_pending', { count }))}</span>
            <button type="button" class="pa-btn primary" data-pa="apply-all">${bridge.icon('check')}<span>${esc(tr('pa_apply_all', { count }))}</span></button>`;
    }

    function autosize() {
        if (!el) return;
        el.input.style.height = 'auto';
        el.input.style.height = `${Math.min(el.input.scrollHeight, INPUT_MAX)}px`;
    }

    function scrollEnd(force) {
        if (!el || (!stick && !force)) return;
        el.log.scrollTop = el.log.scrollHeight;
        el.jump.hidden = true;
    }

    function onScroll() {
        const gap = el.log.scrollHeight - el.log.scrollTop - el.log.clientHeight;
        stick = gap < STICK_PX;
        el.jump.hidden = stick;
    }

    function syncTyping() {
        if (!el) return;
        const typing = el.log.querySelector('[data-key="typing"]');
        const want = !!stream && !stream.textKey;
        if (typing && (!want || typing !== el.log.lastElementChild)) typing.remove();
        if (want && !el.log.querySelector('[data-key="typing"]')) el.log.insertAdjacentHTML('beforeend', typingHtml());
    }

    function place(item) {
        if (!el) return;
        if (el.log.querySelector('.pa-empty')) {
            renderLog();
            scrollEnd();
            return;
        }
        const node = el.log.querySelector(`[data-key="${CSS.escape(item.key)}"]`);
        const html = itemHtml(item);
        if (node) {
            const active = node.contains(document.activeElement) ? document.activeElement.dataset.pa : null;
            node.outerHTML = html;
            if (active) el.log.querySelector(`[data-key="${CSS.escape(item.key)}"] [data-pa="${active}"]`)?.focus({ preventScroll: true });
        } else {
            const typing = el.log.querySelector('[data-key="typing"]');
            if (typing) typing.insertAdjacentHTML('beforebegin', html);
            else el.log.insertAdjacentHTML('beforeend', html);
        }
        syncTyping();
        scrollEnd();
    }

    function push(item) {
        item.key ||= `i${++chat.n}`;
        chat.items.push(item);
        place(item);
        save();
        return item;
    }

    function refreshProposals() {
        pageCache = new Map();
        if (!el || !chat) return;
        chat.items.filter(item => item.type === 'proposal').forEach(item => {
            const node = el.log.querySelector(`[data-key="p:${CSS.escape(item.id)}"]`);
            const p = chat.proposals[item.id];
            if (!node || !p) return;
            const active = node.contains(document.activeElement) ? document.activeElement.dataset.pa : null;
            node.outerHTML = cardHtml(p);
            const next = el.log.querySelector(`[data-key="p:${CSS.escape(item.id)}"]`);
            if (active) (next.querySelector(`[data-pa="${active}"]`) || next.querySelector('[data-pa="show"]'))?.focus({ preventScroll: true });
        });
        renderBulk();
    }

    function updateText(item) {
        dirty.add(item);
        if (frame) return;
        frame = requestAnimationFrame(() => {
            frame = 0;
            const items = [...dirty];
            dirty = new Set();
            items.forEach(next => {
                const node = el?.log.querySelector(`[data-key="${CSS.escape(next.key)}"] .pa-bubble`);
                if (node) node.innerHTML = markdown(next.text);
                else place(next);
            });
            scrollEnd();
        });
    }

    function setScope(kind) {
        if (!SCOPES.includes(kind)) return;
        chat.scope.kind = kind;
        if (kind === 'selection') chat.selection = bridge.selection() || chat.selection;
        if (el) {
            if (el.scope.value !== kind) el.scope.value = kind;
            el.pages.hidden = kind !== 'pages';
            el.note.innerHTML = scopeNote();
            if (kind === 'pages') el.pages.focus();
        }
        save();
    }

    function parsePages(text, order) {
        const ids = [];
        String(text || '').split(/[,;\s]+/).forEach(part => {
            const m = part.match(/^(\d+)(?:\s*[-–]\s*(\d+))?$/);
            if (!m) return;
            const from = Number(m[1]);
            const to = Number(m[2] || m[1]);
            for (let n = Math.min(from, to); n <= Math.max(from, to) && n <= order.length; n++) {
                const id = order[n - 1];
                if (id !== undefined && !ids.includes(id)) ids.push(id);
            }
        });
        return ids;
    }

    function requestScope() {
        const session = bridge.session();
        const kind = chat.scope.kind;
        if (!session) return null;
        if (kind === 'page') return { kind, pages: [session.current], block_ids: [] };
        if (kind === 'document') return { kind, pages: session.order.slice(), block_ids: [] };
        if (kind === 'pages') {
            const pages = parsePages(chat.scope.pages, session.order);
            return pages.length ? { kind, pages, block_ids: [] } : null;
        }
        const sel = currentSelection();
        return sel ? { kind, pages: [sel.page], block_ids: [] } : null;
    }

    async function ensureSession(signal) {
        if (chat.sessionId) return chat.sessionId;
        const target = chat;
        const res = await fetch(`${API}/sessions`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ file_id: chat.fileId }), signal });
        const body = await res.json().catch(() => ({}));
        const id = body?.data?.session_id ?? body?.session_id;
        if (!res.ok || !id) throw Object.assign(new Error('session'), { code: body?.error?.code, detail: body?.error?.message });
        target.sessionId = id;
        save();
        return id;
    }

    function postMessage(sessionId, payload, signal) {
        return fetch(`${API}/sessions/${encodeURIComponent(sessionId)}/messages`, {
            method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' }, body: JSON.stringify(payload), signal
        });
    }

    function dispatch(chunk, onEvent) {
        let type = 'message';
        const data = [];
        chunk.split('\n').forEach(line => {
            if (!line || line.startsWith(':')) return;
            const colon = line.indexOf(':');
            const field = colon < 0 ? line : line.slice(0, colon);
            const value = colon < 0 ? '' : line.slice(colon + 1).replace(/^ /, '');
            if (field === 'event') type = value;
            else if (field === 'data') data.push(value);
        });
        if (!data.length) return;
        try {
            onEvent(type, JSON.parse(data.join('\n')));
        } catch (err) {
            console.error(err);
        }
    }

    async function readStream(body, onEvent) {
        const reader = body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        for (;;) {
            const { value, done } = await reader.read();
            buffer = (buffer + decoder.decode(value || new Uint8Array(), { stream: !done })).replace(/\r\n?/g, '\n');
            let index = buffer.indexOf('\n\n');
            while (index >= 0) {
                dispatch(buffer.slice(0, index), onEvent);
                buffer = buffer.slice(index + 2);
                index = buffer.indexOf('\n\n');
            }
            if (done) {
                if (buffer.trim()) dispatch(buffer, onEvent);
                return;
            }
        }
    }

    function termsOf(list) {
        if (!Array.isArray(list)) return [];
        return list.filter(pair => Array.isArray(pair) && pair.length === 2).slice(0, 60).map(([term, target]) => [String(term), String(target)]);
    }

    function termsHtml(p) {
        if (!p.terms?.length) return '';
        const rows = p.terms.map(([term, target]) => `<li><span>${esc(term)}</span><span class="pa-terms-arrow" aria-hidden="true">→</span><span>${esc(target)}</span></li>`).join('');
        return `<details class="pa-terms"><summary>${esc(tr('pa_terms', { count: p.terms.length }))}</summary><ul>${rows}</ul></details>`;
    }

    function addProposal(data, turn) {
        if (!data?.id || chat.proposals[data.id]) return null;
        const p = {
            id: String(data.id), kind: data.kind || 'text', page: Number(data.page), title: data.title || tr('pa_untitled'), reason: data.reason || '',
            before: data.before || '', after: data.after || '', rects: Array.isArray(data.rects) ? data.rects : [], ops: Array.isArray(data.ops) ? data.ops : [],
            base: data.base || null, depends_on: Array.isArray(data.depends_on) ? data.depends_on.map(String) : [], terms: termsOf(data.terms), turn, seq: ++chat.seq, rejected: false, by: null
        };
        chat.proposals[p.id] = p;
        chainCache = new Map();
        return p;
    }

    function handle(run, type, data) {
        if (stream !== run || chat !== run.chat) return;
        if (type === 'task') {
            run.taskId = data.task_id;
            if (typeof PdfProgress !== 'undefined' && data.task_id) PdfProgress.track(data.task_id);
        } else if (type === 'delta') {
            if (!data.text) return;
            let item = run.textKey && chat.items.find(i => i.key === run.textKey);
            if (!item) {
                run.textKey = 'pending';
                item = push({ type: 'assistant', text: '', streaming: true, turn: run.turn });
                run.textKey = item.key;
                run.texts.push(item);
            }
            item.text += data.text;
            updateText(item);
            save();
        } else if (type === 'tool') {
            const item = chat.items.find(i => i.type === 'tool' && i.turn === run.turn && i.call_id === data.call_id);
            if (item) {
                Object.assign(item, { status: data.status || item.status, summary: data.summary || item.summary, done: Number(data.done) || 0, total: Number(data.total) || 0 });
                place(item);
                save();
            } else {
                closeText(run);
                push({ type: 'tool', call_id: data.call_id, name: data.name || '', args: data.args || {}, status: data.status || 'start', summary: data.summary || '', done: Number(data.done) || 0, total: Number(data.total) || 0, turn: run.turn });
            }
        } else if (type === 'proposal') {
            closeText(run);
            const p = addProposal(data, run.turn);
            if (p) {
                push({ type: 'proposal', id: p.id, key: `p:${p.id}`, turn: run.turn });
                renderBulk();
            }
        } else if (type === 'message') {
            finalText(run, String(data.text || ''));
        } else if (type === 'done') {
            run.done = true;
            if (data.stopped) run.stopped = true;
        } else if (type === 'error') {
            closeText(run);
            run.failed = true;
            if (data.code === 'err_ai_llm_offline' || data.code === 'err_ai_llm_model_missing') {
                status = { ...(status && status !== 'loading' ? status : {}), status: data.code.slice(7) };
                renderHeader();
            }
            push({ type: 'error', code: data.code || '', message: data.message || '', turn: run.turn });
        }
    }

    function closeText(run) {
        const item = run.textKey && chat.items.find(i => i.key === run.textKey);
        if (item) {
            item.streaming = false;
            place(item);
        }
        run.textKey = null;
        syncTyping();
    }

    function finalText(run, text) {
        if (!text.trim()) return;
        const streamed = run.texts.map(item => item.text).join('').replace(/\s+/g, ' ').trim();
        const final = text.replace(/\s+/g, ' ').trim();
        if (streamed.includes(final)) return;
        const last = run.texts[run.texts.length - 1];
        if (last && last === chat.items[chat.items.length - 1] && final.startsWith(last.text.replace(/\s+/g, ' ').trim())) {
            last.text = text;
            last.streaming = false;
            place(last);
        } else {
            closeText(run);
            run.texts.push(push({ type: 'assistant', text, turn: run.turn }));
        }
        save();
    }

    async function send(raw) {
        const text = String(raw || '').trim();
        if (!chat || !text || stream || !ready()) return;
        const scope = requestScope();
        if (!scope) {
            if (el) {
                el.note.innerHTML = chat.scope.kind === 'pages' ? `<span class="pa-warn">${esc(tr('pa_pages_invalid'))}</span>` : scopeNote();
                (chat.scope.kind === 'pages' ? el.pages : el.input).focus();
            }
            return;
        }
        const selection = bridge.selection() || (scope.kind === 'selection' ? chat.selection : null);
        chat.turn++;
        const run = { chat, turn: chat.turn, controller: new AbortController(), textKey: null, texts: [], taskId: null, done: false, stopped: false, failed: false };
        stream = run;
        stick = true;
        push({ type: 'user', text, scope: scope.kind, turn: run.turn });
        if (el) {
            el.input.value = '';
            chat.draft = '';
            autosize();
        }
        renderCompose();
        syncTyping();
        scrollEnd(true);
        const payload = { text, ops: bridge.ops(), scope, selection };
        const onEvent = (type, data) => handle(run, type, data);
        try {
            let sessionId = await ensureSession(run.controller.signal);
            let res = await postMessage(sessionId, payload, run.controller.signal);
            if (res.status === 404 || res.status === 410) {
                chat.sessionId = null;
                sessionId = await ensureSession(run.controller.signal);
                res = await postMessage(sessionId, payload, run.controller.signal);
            }
            if (res.status === 409) onEvent('error', { code: 'pa_err_busy', message: '' });
            else if (res.ok && (res.headers.get('content-type') || '').includes('text/event-stream') && res.body) await readStream(res.body, onEvent);
            else {
                const body = await res.json().catch(() => ({}));
                onEvent('error', { code: body?.error?.code || '', message: body?.error?.message || '' });
            }
        } catch (err) {
            if (err.name !== 'AbortError') onEvent('error', { code: err.code || '', message: err.detail || '' });
        } finally {
            finish(run);
        }
    }

    function finish(run) {
        if (stream !== run) return;
        if (run.chat === chat) {
            closeText(run);
            chat.items.forEach(item => {
                if (item.streaming) item.streaming = false;
                if (item.type === 'tool' && item.turn === run.turn && ['start', 'progress'].includes(item.status)) {
                    item.status = run.stopped ? 'stopped' : 'error';
                    place(item);
                }
            });
            stream = null;
            if (run.stopped) push({ type: 'note', textKey: 'pa_stopped', turn: run.turn });
            else if (!run.done && !run.failed) push({ type: 'error', code: 'pa_err_interrupted', message: '', turn: run.turn });
            syncTyping();
            refreshProposals();
            persist();
        } else {
            stream = null;
        }
        renderCompose();
        const active = document.activeElement;
        if (el && !bridge.compact() && el.slot.offsetParent && (!active || active === document.body || el.root.contains(active))) el.input.focus({ preventScroll: true });
    }

    function stop() {
        const run = stream;
        if (!run) return;
        run.stopped = true;
        if (run.chat.sessionId) bridge.postJson(`${API}/sessions/${encodeURIComponent(run.chat.sessionId)}/stop`, {}).catch(() => null);
        run.controller.abort();
    }

    function suggest(key) {
        const entry = SUGGESTIONS.find(s => s.key === key);
        if (!entry || !el) return;
        setScope(entry.scope);
        const prompt = tr(`pa_s_${key}_prompt`);
        if (entry.send) return send(prompt);
        el.input.value = prompt;
        autosize();
        el.input.focus();
        el.input.setSelectionRange(prompt.length, prompt.length);
    }

    async function refreshStatus(force) {
        if (status === 'loading' || (!force && status?.status === 'ok')) return;
        status = 'loading';
        renderHeader();
        let next;
        try {
            const res = await fetch(`${API}/status`);
            const body = await res.json().catch(() => ({}));
            const data = body?.data || body;
            next = res.ok && data?.status ? data : { status: 'unavailable' };
        } catch (err) {
            next = { status: 'unavailable' };
        }
        status = next;
        renderHeader();
    }

    function newChat() {
        if (!chat) return;
        const session = bridge.session();
        if (!session) return;
        if (stream) stop();
        stream = null;
        forget(chat.digest);
        const scope = { ...chat.scope };
        chat = freshChat(session);
        chat.scope = scope;
        chainCache = new Map();
        unhover();
        if (el) el.input.value = '';
        render();
        persist();
        if (ready()) ensureSession().catch(() => null);
        focusInput();
    }

    function focusInput() {
        if (!el) return;
        if (bridge.compact()) el.root.querySelector('#paTitle').focus({ preventScroll: true });
        else el.input.focus({ preventScroll: true });
    }

    function toggle(open) {
        if (!bridge.session()) return;
        opening = true;
        bridge.side(open);
        opening = false;
    }

    function closePanel() {
        bridge.side(false);
    }

    function onClick(e) {
        const target = e.target.closest('[data-pa]');
        if (!target || target.disabled) return;
        const action = target.dataset.pa;
        const p = target.dataset.id ? chat.proposals[target.dataset.id] : null;
        if (action === 'close') closePanel();
        else if (action === 'new') newChat();
        else if (action === 'retry') refreshStatus(true);
        else if (action === 'jump') {
            stick = true;
            scrollEnd(true);
        } else if (action === 'suggest') suggest(target.dataset.key);
        else if (action === 'apply-all') {
            const list = proposals().filter(q => stateOf(q) === 'pending');
            apply(list, tr('pa_apply_all_label', { count: list.length }));
        } else if (p && action === 'apply') apply([p], tr('pa_apply_label', { title: titleOf(p) }));
        else if (p && action === 'reject') reject(p);
        else if (p && action === 'show') show(p);
    }

    function onKeyDown(e) {
        if (e.key === 'Enter' && e.target === el.input && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            if (!stream) send(el.input.value);
            return;
        }
        if (e.key === 'Enter' && e.target === el.pages) {
            e.preventDefault();
            el.input.focus();
            return;
        }
        if (e.key === 'Escape' && !e.defaultPrevented && bridge.compact()) {
            e.preventDefault();
            e.stopPropagation();
            closePanel();
        }
    }

    function markDoomed(id) {
        el.log.querySelectorAll('.pa-card.doomed').forEach(node => node.classList.remove('doomed'));
        const p = id && chat.proposals[id];
        if (!p) return;
        openDependents(p).forEach(q => el.log.querySelector(`[data-key="p:${CSS.escape(q.id)}"]`)?.classList.add('doomed'));
    }

    function onPointerOver(e) {
        const reject = e.target.closest('[data-pa="reject"]');
        markDoomed(reject?.dataset.id);
        if (e.pointerType !== 'mouse') return;
        const card = e.target.closest('.pa-card');
        const p = card && chat.proposals[card.dataset.id];
        if (p) hover(p);
    }

    function onPointerOut(e) {
        if (e.relatedTarget instanceof Element && e.relatedTarget.closest('[data-pa="reject"]')) return;
        markDoomed(null);
        if (e.pointerType !== 'mouse') return;
        const card = e.target.closest('.pa-card');
        if (card && !(e.relatedTarget instanceof Element && card.contains(e.relatedTarget))) unhover();
    }

    function onCardFocus(e) {
        const reject = e.target.closest('[data-pa="reject"]');
        markDoomed(reject?.dataset.id);
    }

    function onGrab(e) {
        if (!bridge.compact() || !e.target.closest('[data-pa-grab]') || e.target.closest('button, input, select, textarea')) return;
        const sheet = el.slot;
        const startY = e.clientY;
        let dy = 0;
        sheet.setPointerCapture?.(e.pointerId);
        sheet.style.transition = 'none';
        const move = ev => {
            dy = Math.max(0, ev.clientY - startY);
            sheet.style.transform = dy ? `translateY(${dy}px)` : '';
        };
        const end = () => {
            sheet.removeEventListener('pointermove', move);
            sheet.removeEventListener('pointerup', end);
            sheet.removeEventListener('pointercancel', end);
            sheet.style.transition = '';
            sheet.style.transform = '';
            if (dy > 90) closePanel();
        };
        sheet.addEventListener('pointermove', move);
        sheet.addEventListener('pointerup', end);
        sheet.addEventListener('pointercancel', end);
    }

    function onOpen(session) {
        if (!session?.digest) return;
        chat = load(session);
        applied = new Set(bridge.ops().map(op => op.proposal).filter(Boolean));
        pageCache = new Map();
        chainCache = new Map();
        stream = null;
        el = null;
    }

    function onClose() {
        if (stream) stop();
        stream = null;
        persist();
        unhover();
        chat = null;
        el = null;
        const slot = bridge.sheetSlot();
        if (slot) slot.innerHTML = '';
    }

    function onOps({ ops }) {
        applied = new Set((ops || []).map(op => op.proposal).filter(Boolean));
        refreshProposals();
    }

    function onSide({ open }) {
        const button = bridge.button('agent');
        button?.setAttribute('aria-pressed', open ? 'true' : 'false');
        if (!open) {
            unhover();
            const target = button && button.offsetParent ? button : document.getElementById('peMoreBtn');
            if (el?.root.contains(document.activeElement)) target?.focus({ preventScroll: true });
            return;
        }
        if (!chat) {
            const session = bridge.session();
            if (!session?.digest) return;
            onOpen(session);
        }
        if (!el || el.digest !== chat.digest || !el.slot.contains(el.root)) render();
        else refreshProposals();
        refreshStatus(false);
        if (opening) requestAnimationFrame(focusInput);
    }

    function onPage() {
        if (el && chat?.scope.kind === 'page') el.note.innerHTML = scopeNote();
    }

    function setup() {
        const button = bridge.button('agent');
        if (button) {
            button.hidden = false;
            button.addEventListener('click', () => toggle());
        }
        bridge.addMenuItem({ id: 'agent', icon: bridge.icon('sparkles'), labelKey: 'pe_agent', run: () => toggle(true) });
        document.addEventListener('languagechange', () => el && render());
        window.addEventListener('pagehide', persist);
    }

    bridge.translations({
        en: {
            pa_new_chat: 'New chat',
            pa_scope: 'Scope',
            pa_scope_page: 'This page',
            pa_scope_pages: 'Chosen pages',
            pa_scope_document: 'Whole document',
            pa_scope_selection: 'Selection',
            pa_scope_page_note: 'Working on page {page} of {total}',
            pa_scope_document_note_one: 'Working on the whole document ({count} page)',
            pa_scope_document_note_other: 'Working on the whole document ({count} pages)',
            pa_pages_label: 'Pages',
            pa_pages_placeholder: 'e.g. 1-3, 5',
            pa_pages_invalid: 'Enter page numbers, e.g. 1-3, 5.',
            pa_selection_none: 'Click a text block in the document to use it as the selection.',
            pa_selection_text: 'Selection: “{text}”',
            pa_input: 'Ask the assistant…',
            pa_send: 'Send',
            pa_stop: 'Stop',
            pa_hint: 'Enter to send, Shift+Enter for a new line',
            pa_you: 'You',
            pa_empty_title: 'What should I do with this document?',
            pa_empty_text: 'I read the pages and suggest changes. Nothing is changed until you apply it.',
            pa_s_typos: 'Fix typos on this page',
            pa_s_typos_prompt: 'Fix the typos on this page.',
            pa_s_translate: 'Translate the document to…',
            pa_s_translate_prompt: 'Translate the document to ',
            pa_s_redact: 'Find and redact personal data',
            pa_s_redact_prompt: 'Find and redact all personal data in the document.',
            pa_s_summary: 'Summarize changes',
            pa_s_summary_prompt: 'Summarize the changes made to this document so far.',
            pa_offline: 'Model unavailable',
            pa_status_unavailable: 'The assistant is not available right now.',
            pa_retry: 'Try again',
            pa_thinking: 'Thinking…',
            pa_jump: 'Jump to the latest message',
            pa_show: 'Show',
            pa_apply: 'Apply',
            pa_reject: 'Reject',
            pa_dismiss: 'Dismiss',
            pa_applied: 'Applied',
            pa_rejected: 'Rejected',
            pa_rejected_with: 'Rejected together with “{title}”',
            pa_stale: 'Out of date: the page changed after this suggestion',
            pa_terms: 'Terms used ({count})',
            pa_applies_with_one: 'Also applies {count} earlier change it builds on',
            pa_applies_with_other: 'Also applies {count} earlier changes it builds on',
            pa_rejects_with_one: 'Also rejects {count} change that builds on this one',
            pa_rejects_with_other: 'Also rejects {count} changes that build on this one',
            pa_pending_one: '{count} suggestion waiting',
            pa_pending_other: '{count} suggestions waiting',
            pa_apply_all: 'Apply all ({count})',
            pa_apply_label: 'AI: {title}',
            pa_apply_all_label_one: 'AI: {count} change',
            pa_apply_all_label_other: 'AI: {count} changes',
            pa_untitled: 'Suggested change',
            pa_title_text: 'Text fix', pa_title_style: 'Style change', pa_title_insert: 'New text', pa_title_delete: 'Text removal',
            pa_title_annot: 'Annotation', pa_title_redact: 'Redaction', pa_title_page: 'Page change',
            pa_tool_progress: '{done}/{total}',
            pa_err_busy: 'The assistant is still working on the previous message.',
            pa_stopped: 'Stopped.',
            pa_err_generic: 'Something went wrong. Try again.',
            pa_err_interrupted: 'The answer was interrupted. Try again.',
            err_agent_steps: 'The assistant reached its step limit. Try a narrower request.',
            err_agent_failed: 'The assistant could not finish. Try again.',
            err_agent_context: 'This request is too large. Narrow the scope and try again.',
            pa_kind_text: 'Text', pa_kind_style: 'Style', pa_kind_insert: 'Insert', pa_kind_delete: 'Delete',
            pa_kind_annot: 'Annotation', pa_kind_redact: 'Redaction', pa_kind_page: 'Page',
            pa_tool_list_pages: 'Listing pages', pa_tool_read_page: 'Reading page', pa_tool_search: 'Searching',
            pa_tool_replace_text: 'Rewriting text', pa_tool_proofread: 'Proofreading', pa_tool_set_style: 'Styling text',
            pa_tool_insert_text: 'Inserting text', pa_tool_delete_text: 'Deleting text', pa_tool_highlight: 'Highlighting',
            pa_tool_add_note: 'Adding a note', pa_tool_redact: 'Redacting', pa_tool_translate: 'Translating',
            pa_tool_page_action: 'Changing pages', pa_tool_finish: 'Finishing'
        },
        pl: {
            pa_new_chat: 'Nowa rozmowa',
            pa_scope: 'Zakres',
            pa_scope_page: 'Ta strona',
            pa_scope_pages: 'Wybrane strony',
            pa_scope_document: 'Cały dokument',
            pa_scope_selection: 'Zaznaczenie',
            pa_scope_page_note: 'Strona {page} z {total}',
            pa_scope_document_note_one: 'Cały dokument ({count} strona)',
            pa_scope_document_note_few: 'Cały dokument ({count} strony)',
            pa_scope_document_note_many: 'Cały dokument ({count} stron)',
            pa_scope_document_note_other: 'Cały dokument ({count} strony)',
            pa_pages_label: 'Strony',
            pa_pages_placeholder: 'np. 1-3, 5',
            pa_pages_invalid: 'Podaj numery stron, np. 1-3, 5.',
            pa_selection_none: 'Kliknij blok tekstu w dokumencie, żeby użyć go jako zaznaczenia.',
            pa_selection_text: 'Zaznaczenie: „{text}”',
            pa_input: 'Napisz do asystenta…',
            pa_send: 'Wyślij',
            pa_stop: 'Zatrzymaj',
            pa_hint: 'Enter wysyła, Shift+Enter dodaje nową linię',
            pa_you: 'Ty',
            pa_empty_title: 'Co mam zrobić z tym dokumentem?',
            pa_empty_text: 'Czytam strony i proponuję zmiany. Nic się nie zmieni, dopóki ich nie zastosujesz.',
            pa_s_typos: 'Popraw literówki na tej stronie',
            pa_s_typos_prompt: 'Popraw literówki na tej stronie.',
            pa_s_translate: 'Przetłumacz dokument na…',
            pa_s_translate_prompt: 'Przetłumacz dokument na ',
            pa_s_redact: 'Znajdź i zaczernij dane osobowe',
            pa_s_redact_prompt: 'Znajdź i zaczernij wszystkie dane osobowe w dokumencie.',
            pa_s_summary: 'Podsumuj zmiany',
            pa_s_summary_prompt: 'Podsumuj dotychczasowe zmiany w tym dokumencie.',
            pa_offline: 'Model niedostępny',
            pa_status_unavailable: 'Asystent jest teraz niedostępny.',
            pa_retry: 'Spróbuj ponownie',
            pa_thinking: 'Myślę…',
            pa_jump: 'Przejdź do najnowszej wiadomości',
            pa_show: 'Pokaż',
            pa_apply: 'Zastosuj',
            pa_reject: 'Odrzuć',
            pa_dismiss: 'Ukryj',
            pa_applied: 'Zastosowano',
            pa_rejected: 'Odrzucono',
            pa_rejected_with: 'Odrzucono razem z „{title}”',
            pa_stale: 'Nieaktualne: strona zmieniła się po tej propozycji',
            pa_terms: 'Użyte terminy ({count})',
            pa_applies_with_one: 'Zastosuje też {count} wcześniejszą zmianę, na której bazuje',
            pa_applies_with_few: 'Zastosuje też {count} wcześniejsze zmiany, na których bazuje',
            pa_applies_with_many: 'Zastosuje też {count} wcześniejszych zmian, na których bazuje',
            pa_applies_with_other: 'Zastosuje też {count} wcześniejszej zmiany, na których bazuje',
            pa_rejects_with_one: 'Odrzuci też {count} zmianę, która z niej wynika',
            pa_rejects_with_few: 'Odrzuci też {count} zmiany, które z niej wynikają',
            pa_rejects_with_many: 'Odrzuci też {count} zmian, które z niej wynikają',
            pa_rejects_with_other: 'Odrzuci też {count} zmiany, które z niej wynikają',
            pa_pending_one: '{count} propozycja czeka',
            pa_pending_few: '{count} propozycje czekają',
            pa_pending_many: '{count} propozycji czeka',
            pa_pending_other: '{count} propozycji czeka',
            pa_apply_all: 'Zastosuj wszystkie ({count})',
            pa_apply_label: 'AI: {title}',
            pa_apply_all_label_one: 'AI: {count} zmiana',
            pa_apply_all_label_few: 'AI: {count} zmiany',
            pa_apply_all_label_many: 'AI: {count} zmian',
            pa_apply_all_label_other: 'AI: {count} zmiany',
            pa_untitled: 'Proponowana zmiana',
            pa_title_text: 'Poprawka tekstu', pa_title_style: 'Zmiana stylu', pa_title_insert: 'Nowy tekst', pa_title_delete: 'Usunięcie tekstu',
            pa_title_annot: 'Adnotacja', pa_title_redact: 'Zaczernienie', pa_title_page: 'Zmiana strony',
            pa_tool_progress: '{done}/{total}',
            pa_err_busy: 'Asystent wciąż pracuje nad poprzednią wiadomością.',
            pa_stopped: 'Zatrzymano.',
            pa_err_generic: 'Coś poszło nie tak. Spróbuj ponownie.',
            pa_err_interrupted: 'Odpowiedź została przerwana. Spróbuj ponownie.',
            err_agent_steps: 'Asystent wykorzystał limit kroków. Zawęź polecenie.',
            err_agent_failed: 'Asystent nie dokończył zadania. Spróbuj ponownie.',
            err_agent_context: 'To polecenie jest za duże. Zawęź zakres i spróbuj ponownie.',
            pa_kind_text: 'Tekst', pa_kind_style: 'Styl', pa_kind_insert: 'Wstawienie', pa_kind_delete: 'Usunięcie',
            pa_kind_annot: 'Adnotacja', pa_kind_redact: 'Zaczernienie', pa_kind_page: 'Strona',
            pa_tool_list_pages: 'Przeglądam strony', pa_tool_read_page: 'Czytam stronę', pa_tool_search: 'Szukam',
            pa_tool_replace_text: 'Przepisuję tekst', pa_tool_proofread: 'Sprawdzam pisownię', pa_tool_set_style: 'Zmieniam styl',
            pa_tool_insert_text: 'Wstawiam tekst', pa_tool_delete_text: 'Usuwam tekst', pa_tool_highlight: 'Zaznaczam',
            pa_tool_add_note: 'Dodaję notatkę', pa_tool_redact: 'Zaczerniam', pa_tool_translate: 'Tłumaczę',
            pa_tool_page_action: 'Zmieniam strony', pa_tool_finish: 'Kończę'
        },
        de: {
            pa_new_chat: 'Neuer Chat',
            pa_scope: 'Bereich',
            pa_scope_page: 'Diese Seite',
            pa_scope_pages: 'Ausgewählte Seiten',
            pa_scope_document: 'Ganzes Dokument',
            pa_scope_selection: 'Auswahl',
            pa_scope_page_note: 'Seite {page} von {total}',
            pa_scope_document_note_one: 'Ganzes Dokument ({count} Seite)',
            pa_scope_document_note_other: 'Ganzes Dokument ({count} Seiten)',
            pa_pages_label: 'Seiten',
            pa_pages_placeholder: 'z. B. 1-3, 5',
            pa_pages_invalid: 'Seitenzahlen eingeben, z. B. 1-3, 5.',
            pa_selection_none: 'Klicke auf einen Textblock im Dokument, um ihn als Auswahl zu verwenden.',
            pa_selection_text: 'Auswahl: „{text}“',
            pa_input: 'Frag den Assistenten…',
            pa_send: 'Senden',
            pa_stop: 'Stopp',
            pa_hint: 'Enter sendet, Umschalt+Enter fügt eine neue Zeile ein',
            pa_you: 'Du',
            pa_empty_title: 'Was soll ich mit diesem Dokument tun?',
            pa_empty_text: 'Ich lese die Seiten und schlage Änderungen vor. Nichts ändert sich, bevor du es übernimmst.',
            pa_s_typos: 'Tippfehler auf dieser Seite korrigieren',
            pa_s_typos_prompt: 'Korrigiere die Tippfehler auf dieser Seite.',
            pa_s_translate: 'Dokument übersetzen nach…',
            pa_s_translate_prompt: 'Übersetze das Dokument nach ',
            pa_s_redact: 'Personendaten finden und schwärzen',
            pa_s_redact_prompt: 'Finde und schwärze alle personenbezogenen Daten im Dokument.',
            pa_s_summary: 'Änderungen zusammenfassen',
            pa_s_summary_prompt: 'Fasse die bisherigen Änderungen an diesem Dokument zusammen.',
            pa_offline: 'Modell nicht verfügbar',
            pa_status_unavailable: 'Der Assistent ist gerade nicht verfügbar.',
            pa_retry: 'Erneut versuchen',
            pa_thinking: 'Denke nach…',
            pa_jump: 'Zur neuesten Nachricht',
            pa_show: 'Zeigen',
            pa_apply: 'Übernehmen',
            pa_reject: 'Ablehnen',
            pa_dismiss: 'Ausblenden',
            pa_applied: 'Übernommen',
            pa_rejected: 'Abgelehnt',
            pa_rejected_with: 'Zusammen mit „{title}“ abgelehnt',
            pa_stale: 'Veraltet: Die Seite hat sich nach diesem Vorschlag geändert',
            pa_terms: 'Verwendete Begriffe ({count})',
            pa_applies_with_one: 'Übernimmt auch {count} frühere Änderung, auf der er aufbaut',
            pa_applies_with_other: 'Übernimmt auch {count} frühere Änderungen, auf denen er aufbaut',
            pa_rejects_with_one: 'Lehnt auch {count} darauf aufbauende Änderung ab',
            pa_rejects_with_other: 'Lehnt auch {count} darauf aufbauende Änderungen ab',
            pa_pending_one: '{count} Vorschlag wartet',
            pa_pending_other: '{count} Vorschläge warten',
            pa_apply_all: 'Alle übernehmen ({count})',
            pa_apply_label: 'KI: {title}',
            pa_apply_all_label_one: 'KI: {count} Änderung',
            pa_apply_all_label_other: 'KI: {count} Änderungen',
            pa_untitled: 'Vorgeschlagene Änderung',
            pa_title_text: 'Textkorrektur', pa_title_style: 'Stiländerung', pa_title_insert: 'Neuer Text', pa_title_delete: 'Text entfernen',
            pa_title_annot: 'Anmerkung', pa_title_redact: 'Schwärzung', pa_title_page: 'Seitenänderung',
            pa_tool_progress: '{done}/{total}',
            pa_err_busy: 'Der Assistent arbeitet noch an der vorherigen Nachricht.',
            pa_stopped: 'Gestoppt.',
            pa_err_generic: 'Etwas ist schiefgelaufen. Bitte erneut versuchen.',
            pa_err_interrupted: 'Die Antwort wurde unterbrochen. Bitte erneut versuchen.',
            err_agent_steps: 'Der Assistent hat sein Schrittlimit erreicht. Formuliere die Anfrage enger.',
            err_agent_failed: 'Der Assistent konnte nicht fertig werden. Bitte erneut versuchen.',
            err_agent_context: 'Diese Anfrage ist zu groß. Grenze den Bereich ein und versuche es erneut.',
            pa_kind_text: 'Text', pa_kind_style: 'Stil', pa_kind_insert: 'Einfügen', pa_kind_delete: 'Löschen',
            pa_kind_annot: 'Anmerkung', pa_kind_redact: 'Schwärzung', pa_kind_page: 'Seite',
            pa_tool_list_pages: 'Seiten auflisten', pa_tool_read_page: 'Seite lesen', pa_tool_search: 'Suchen',
            pa_tool_replace_text: 'Text umschreiben', pa_tool_proofread: 'Korrektur lesen', pa_tool_set_style: 'Stil ändern',
            pa_tool_insert_text: 'Text einfügen', pa_tool_delete_text: 'Text löschen', pa_tool_highlight: 'Markieren',
            pa_tool_add_note: 'Notiz hinzufügen', pa_tool_redact: 'Schwärzen', pa_tool_translate: 'Übersetzen',
            pa_tool_page_action: 'Seiten ändern', pa_tool_finish: 'Abschließen'
        }
    });

    bridge.on('open', onOpen);
    bridge.on('close', onClose);
    bridge.on('ops', onOps);
    bridge.on('side', onSide);
    bridge.on('page', onPage);
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setup, { once: true });
    else setup();

    return { open: () => toggle(true), close: closePanel, send, stop, newChat };
})();

const CustomSelect = (() => {
    const CHEVRON = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    const CHECK = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
    const valueDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value');
    const indexDesc = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'selectedIndex');
    const instances = new WeakMap();
    let open = null;
    let uid = 0;

    function eligible(select) {
        return !instances.has(select) && !select.multiple && !(select.size > 1) && !select.hasAttribute('data-native');
    }

    function enhance(select) {
        if (!eligible(select)) return;
        const id = `cselect-${++uid}`;
        const trigger = document.createElement('button');
        trigger.type = 'button';
        trigger.setAttribute('aria-haspopup', 'listbox');
        trigger.setAttribute('aria-expanded', 'false');
        trigger.setAttribute('aria-controls', id);
        trigger.innerHTML = `<span class="cselect-value"></span><span class="cselect-chevron">${CHEVRON}</span>`;
        const label = trigger.firstChild;

        const state = { select, trigger, id };
        instances.set(select, state);

        function syncClasses() {
            const classes = [...select.classList].filter(name => name !== 'cselect-native');
            trigger.className = [...classes, 'cselect-trigger'].join(' ');
        }

        function sync() {
            const option = select.options[select.selectedIndex];
            label.textContent = option ? option.textContent : '';
            trigger.disabled = select.disabled;
            const aria = select.getAttribute('aria-label');
            if (aria) trigger.setAttribute('aria-label', `${aria}: ${label.textContent}`);
            if (select.title) trigger.title = select.title;
            if (open === state) render(state);
        }
        state.sync = sync;

        Object.defineProperty(select, 'value', {
            configurable: true,
            get() { return valueDesc.get.call(this); },
            set(v) { valueDesc.set.call(this, v); sync(); }
        });
        Object.defineProperty(select, 'selectedIndex', {
            configurable: true,
            get() { return indexDesc.get.call(this); },
            set(v) { indexDesc.set.call(this, v); sync(); }
        });

        syncClasses();
        select.classList.add('cselect-native');
        select.tabIndex = -1;
        select.setAttribute('aria-hidden', 'true');
        select.after(trigger);
        sync();

        new MutationObserver(records => {
            if (records.some(r => r.target === select && r.attributeName === 'class')) syncClasses();
            sync();
        }).observe(select, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ['class', 'disabled', 'aria-label', 'title', 'selected', 'label'] });

        select.addEventListener('change', sync);
        select.addEventListener('focus', () => trigger.focus());
        trigger.addEventListener('click', event => {
            event.stopPropagation();
            open === state ? close() : show(state);
        });
        trigger.addEventListener('keydown', event => onTriggerKey(state, event));
    }

    function options(state) {
        return [...state.select.options].filter(option => !option.hidden);
    }

    function render(state) {
        const menu = state.menu;
        const current = state.select.value;
        menu.innerHTML = '';
        options(state).forEach((option, index) => {
            const item = document.createElement('div');
            item.className = 'cselect-option';
            item.id = `${state.id}-${index}`;
            item.setAttribute('role', 'option');
            item.dataset.value = option.value;
            const selected = option.value === current;
            item.setAttribute('aria-selected', String(selected));
            if (option.disabled) item.setAttribute('aria-disabled', 'true');
            item.innerHTML = `<span class="cselect-option-label"></span><span class="cselect-check">${selected ? CHECK : ''}</span>`;
            item.firstChild.textContent = option.textContent;
            menu.appendChild(item);
        });
        highlight(state, state.active ?? index(state, current));
    }

    function index(state, value) {
        return Math.max(0, options(state).findIndex(option => option.value === value));
    }

    function enabledIndex(state, from, step) {
        const items = options(state);
        for (let i = from; i >= 0 && i < items.length; i += step) {
            if (!items[i].disabled) return i;
        }
        return null;
    }

    function highlight(state, i) {
        const items = state.menu.children;
        if (!items.length) return;
        state.active = Math.min(Math.max(i, 0), items.length - 1);
        [...items].forEach((item, n) => item.classList.toggle('is-active', n === state.active));
        const active = items[state.active];
        state.trigger.setAttribute('aria-activedescendant', active.id);
        const top = active.offsetTop, bottom = top + active.offsetHeight;
        if (top < state.menu.scrollTop) state.menu.scrollTop = top - 4;
        else if (bottom > state.menu.scrollTop + state.menu.clientHeight) state.menu.scrollTop = bottom - state.menu.clientHeight + 4;
    }

    function position(state) {
        const rect = state.trigger.getBoundingClientRect();
        const menu = state.menu;
        const gap = 6, margin = 8;
        const width = Math.min(Math.max(rect.width, 180), window.innerWidth - margin * 2);
        menu.style.minWidth = `${width}px`;
        menu.style.maxWidth = `${Math.max(width, Math.min(360, window.innerWidth - margin * 2))}px`;
        const below = window.innerHeight - rect.bottom - gap - margin;
        const above = rect.top - gap - margin;
        const natural = Math.min(menu.scrollHeight, 320);
        const up = natural > below && above > below;
        menu.style.maxHeight = `${Math.max(120, Math.min(320, up ? above : below))}px`;
        menu.classList.toggle('is-up', up);
        const left = Math.min(Math.max(margin, rect.left), window.innerWidth - margin - menu.offsetWidth);
        menu.style.left = `${left}px`;
        menu.style.top = up ? `${rect.top - gap - menu.offsetHeight}px` : `${rect.bottom + gap}px`;
    }

    function show(state) {
        if (state.trigger.disabled || !options(state).length) return;
        close();
        const menu = document.createElement('div');
        menu.className = 'cselect-menu';
        menu.id = state.id;
        menu.setAttribute('role', 'listbox');
        const fontSize = getComputedStyle(state.trigger).fontSize;
        menu.style.fontSize = fontSize;
        state.menu = menu;
        state.active = null;
        state.typed = '';
        render(state);
        document.body.appendChild(menu);
        position(state);
        highlight(state, index(state, state.select.value));
        menu.addEventListener('mousedown', event => event.preventDefault());
        menu.addEventListener('click', event => {
            const item = event.target.closest('.cselect-option');
            if (!item || item.getAttribute('aria-disabled') === 'true') return;
            choose(state, item.dataset.value);
        });
        menu.addEventListener('mousemove', event => {
            const item = event.target.closest('.cselect-option');
            if (item) highlight(state, [...menu.children].indexOf(item));
        });
        state.trigger.setAttribute('aria-expanded', 'true');
        state.trigger.classList.add('is-open');
        open = state;
        requestAnimationFrame(() => menu.classList.add('is-visible'));
    }

    function close() {
        if (!open) return;
        const state = open;
        open = null;
        state.menu?.remove();
        state.menu = null;
        state.trigger.setAttribute('aria-expanded', 'false');
        state.trigger.removeAttribute('aria-activedescendant');
        state.trigger.classList.remove('is-open');
    }

    function choose(state, value) {
        const changed = state.select.value !== value;
        close();
        state.trigger.focus();
        if (!changed) return;
        state.select.value = value;
        state.select.dispatchEvent(new Event('input', { bubbles: true }));
        state.select.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function typeahead(state, key) {
        clearTimeout(state.typeTimer);
        state.typed = (state.typed || '') + key.toLowerCase();
        state.typeTimer = setTimeout(() => { state.typed = ''; }, 600);
        const items = options(state);
        const start = state.typed.length === 1 ? (state.active ?? -1) + 1 : (state.active ?? 0);
        for (let n = 0; n < items.length; n++) {
            const i = (start + n) % items.length;
            if (!items[i].disabled && items[i].textContent.trim().toLowerCase().startsWith(state.typed)) return i;
        }
        return null;
    }

    function onTriggerKey(state, event) {
        const isOpen = open === state;
        const key = event.key;
        if (!isOpen) {
            if (['ArrowDown', 'ArrowUp', 'Enter', ' '].includes(key)) {
                event.preventDefault();
                show(state);
            } else if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
                const i = typeahead(state, key);
                if (i !== null) choose(state, options(state)[i].value);
            }
            return;
        }
        const count = state.menu.children.length;
        let next = null;
        if (key === 'ArrowDown') next = enabledIndex(state, state.active + 1, 1);
        else if (key === 'ArrowUp') next = enabledIndex(state, state.active - 1, -1);
        else if (key === 'Home') next = enabledIndex(state, 0, 1);
        else if (key === 'End') next = enabledIndex(state, count - 1, -1);
        else if (key === 'PageDown') next = enabledIndex(state, Math.min(count - 1, state.active + 8), 1) ?? enabledIndex(state, count - 1, -1);
        else if (key === 'PageUp') next = enabledIndex(state, Math.max(0, state.active - 8), -1) ?? enabledIndex(state, 0, 1);
        else if (key === 'Enter' || key === ' ') {
            event.preventDefault();
            const item = state.menu.children[state.active];
            if (item && item.getAttribute('aria-disabled') !== 'true') choose(state, item.dataset.value);
            return;
        } else if (key === 'Escape') {
            event.preventDefault();
            close();
            return;
        } else if (key === 'Tab') {
            close();
            return;
        } else if (key.length === 1 && !event.ctrlKey && !event.metaKey && !event.altKey) {
            next = typeahead(state, key);
        }
        if (next !== null || ['ArrowDown', 'ArrowUp', 'Home', 'End', 'PageDown', 'PageUp'].includes(key)) event.preventDefault();
        if (next !== null) highlight(state, next);
    }

    function scan(root) {
        if (root.nodeType !== 1) return;
        if (root.tagName === 'SELECT') enhance(root);
        else root.querySelectorAll('select').forEach(enhance);
    }

    function init() {
        scan(document.body);
        new MutationObserver(records => {
            records.forEach(record => record.addedNodes.forEach(scan));
            if (open && !open.trigger.isConnected) close();
        }).observe(document.body, { childList: true, subtree: true });
        document.addEventListener('mousedown', event => {
            if (open && !open.menu.contains(event.target) && !open.trigger.contains(event.target)) close();
        }, true);
        window.addEventListener('resize', close);
        window.addEventListener('scroll', event => {
            if (open && event.target !== open.menu) position(open);
        }, true);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();

    return { enhance, close };
})();

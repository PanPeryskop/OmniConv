function escapeHtml(value) {
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

class I18n {
    constructor() {
        this.currentLang = this.detectLanguage();
    }

    detectLanguage() {
        let saved = null;
        try { saved = localStorage.getItem('lang'); } catch (e) {}
        if (saved && translations?.[saved]) return saved;
        const browser = (navigator.language || 'en').slice(0, 2).toLowerCase();
        return translations?.[browser] ? browser : 'en';
    }

    lookup(lang, key, vars) {
        const dict = translations?.[lang];
        if (!dict) return undefined;
        if (vars && typeof vars.count === 'number') {
            const rule = new Intl.PluralRules(lang).select(vars.count);
            if (dict[`${key}_${rule}`] !== undefined) return dict[`${key}_${rule}`];
            if (dict[`${key}_other`] !== undefined) return dict[`${key}_other`];
        }
        return dict[key];
    }

    t(key, vars) {
        const fallback = typeof vars === 'string' ? vars : undefined;
        const params = typeof vars === 'object' && vars !== null ? vars : null;
        const template = this.lookup(this.currentLang, key, params) ?? this.lookup('en', key, params) ?? fallback ?? key;
        if (!params) return template;
        return template.replace(/\{(\w+)\}/g, (match, name) => (name in params ? params[name] : match));
    }

    html(key, vars, tag = 'span') {
        const varsAttr = vars ? ` data-i18n-vars="${escapeHtml(JSON.stringify(vars))}"` : '';
        return `<${tag} data-i18n="${key}"${varsAttr}>${escapeHtml(this.t(key, vars))}</${tag}>`;
    }

    set(el, key, vars) {
        if (!el) return;
        el.dataset.i18n = key;
        if (vars) el.dataset.i18nVars = JSON.stringify(vars);
        else delete el.dataset.i18nVars;
        el.textContent = this.t(key, vars);
    }

    setLanguage(lang) {
        if (!translations?.[lang]) return;
        this.currentLang = lang;
        try { localStorage.setItem('lang', lang); } catch (e) {}
        this.apply();
    }

    apply() {
        const lang = this.currentLang;
        const dict = translations?.[lang];
        if (!dict) return;

        document.documentElement.lang = lang;

        document.querySelectorAll('.lang-switch [data-lang]').forEach(btn => {
            const active = btn.dataset.lang === lang;
            btn.classList.toggle('active', active);
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
        });

        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const rawVars = el.getAttribute('data-i18n-vars');
            if (rawVars) {
                let vars = null;
                try { vars = JSON.parse(rawVars); } catch (e) {}
                el.textContent = this.t(key, vars);
                return;
            }
            if (!(key in dict)) return;
            if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                el.placeholder = dict[key];
            } else if (el.tagName === 'TITLE') {
                document.title = dict[key];
            } else {
                el.innerHTML = dict[key];
            }
        });

        document.querySelectorAll('[data-i18n-aria]').forEach(el => {
            const key = el.getAttribute('data-i18n-aria');
            if (dict[key]) el.setAttribute('aria-label', dict[key]);
        });

        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            const key = el.getAttribute('data-i18n-title');
            if (dict[key]) el.setAttribute('title', dict[key]);
        });

        document.querySelectorAll('[data-i18n-alt]').forEach(el => {
            const key = el.getAttribute('data-i18n-alt');
            if (dict[key]) el.setAttribute('alt', dict[key]);
        });

        document.dispatchEvent(new CustomEvent('languagechange', { detail: { lang } }));
    }
}

const i18n = new I18n();
try {
    i18n.apply();
} finally {
    document.documentElement.classList.remove('i18n-pending');
}

function setLanguage(lang) {
    i18n.setLanguage(lang);
}

function t(key, vars) {
    return i18n.t(key, vars);
}

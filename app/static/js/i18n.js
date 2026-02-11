class I18n {
    constructor() {
        this.currentLang = localStorage.getItem('lang') || 'en';
    }

    setLanguage(lang) {
        this.currentLang = lang;
        localStorage.setItem('lang', lang);
        this.apply();
    }

    apply() {
        const lang = this.currentLang;
        const dict = translations?.[lang];
        if (!dict) return;

        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            if (dict[key]) {
                if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
                    el.placeholder = dict[key];
                } else {
                    el.innerHTML = dict[key];
                }
            }
        });

        document.querySelectorAll('[data-i18n-aria]').forEach(el => {
            const key = el.getAttribute('data-i18n-aria');
            if (dict[key]) el.setAttribute('aria-label', dict[key]);
        });
    }
}

const i18n = new I18n();
document.addEventListener('DOMContentLoaded', () => i18n.apply());

function setLanguage(lang) {
    i18n.setLanguage(lang);
}

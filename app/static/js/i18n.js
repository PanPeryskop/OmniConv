class I18n {
    constructor() {
        this.lang = localStorage.getItem('lang') || 'en';
        this.updateTexts();
    }

    setLanguage(lang) {
        if (!translations[lang]) return;
        this.lang = lang;
        localStorage.setItem('lang', lang);
        this.updateTexts();
    }

    updateTexts() {
        document.documentElement.lang = this.lang;
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const text = translations[this.lang][key];
            if (text) {
                if (el.innerHTML.includes('<') && text.includes('<')) {
                     el.innerHTML = text; // Allow HTML replacements
                } else {
                     el.textContent = text;
                }
            }
        });
    }
}

const i18n = new I18n();
window.setLanguage = (lang) => i18n.setLanguage(lang);

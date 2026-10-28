const OcrRapidOptions = (() => {
    const STORAGE_KEY = 'omniconv_ocr_rapid';
    const LANG_TO_SCRIPT = {
        ru: 'eslav', uk: 'eslav', be: 'eslav',
        bg: 'cyrillic', sr: 'cyrillic', mk: 'cyrillic', kk: 'cyrillic', mn: 'cyrillic',
        el: 'el', ar: 'arabic', fa: 'arabic', ur: 'arabic', ko: 'korean', th: 'th',
        hi: 'devanagari', mr: 'devanagari', ne: 'devanagari', ta: 'ta', te: 'te'
    };

    function read() {
        try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {}; } catch (e) { return {}; }
    }

    function write(value) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(value)); } catch (e) {}
    }

    function browserScript() {
        const lang = (navigator.language || '').slice(0, 2).toLowerCase();
        return LANG_TO_SCRIPT[lang] || 'latin';
    }

    function setIfValid(select, value) {
        if (value && [...select.options].some(option => option.value === value)) select.value = value;
    }

    function init(root) {
        if (!root) return null;
        const quality = root.querySelector('[data-ocr-quality]');
        const script = root.querySelector('[data-ocr-script]');
        const hint = root.querySelector('[data-ocr-rapid-hint]');
        const saved = read();
        setIfValid(quality, saved.quality || 'accurate');
        setIfValid(script, saved.script || browserScript());

        function describe() {
            const parts = [t(`ocr_quality_${quality.value}_desc`)];
            if (script.value !== 'latin') parts.push(t('ocr_script_other_desc'));
            hint.textContent = parts.join(' ');
        }

        function changed() {
            write({ quality: quality.value, script: script.value });
            describe();
        }

        quality.addEventListener('change', changed);
        script.addEventListener('change', changed);
        document.addEventListener('languagechange', describe);
        describe();

        return {
            values: () => ({ ocr_quality: quality.value, ocr_script: script.value }),
            setVisible: (visible) => root.classList.toggle('hidden', !visible)
        };
    }

    return { init };
})();

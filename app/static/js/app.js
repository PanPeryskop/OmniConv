const appState = {
    currentFileId: null,
    currentJobId: null,
    fileType: null,
    fileName: null,
    outputFormats: [],
    selectedFormat: null,
    isConverting: false,
    pollInterval: null,
    socket: null,
    ocrEngines: null
};

const CONVERT_ERROR_KEYS = {
    UnsupportedFormatError: 'unsupported_format',
    NotFoundError: 'err_file_missing',
    FileTooLargeError: 'err_too_large',
    NoFileError: 'err_no_file',
    UploadError: 'err_upload_failed',
    DownloadError: 'err_url_failed'
};

function translateError(error, code, fallbackKey) {
    const key = code || error?.code || CONVERT_ERROR_KEYS[error?.type];
    if (key && key in translations.en) return { key };
    if (error?.message) return { message: error.message };
    return { key: fallbackKey };
}

if (typeof io !== 'undefined') {
    appState.socket = io();
    appState.socket.on('conversion_progress', (data) => {
        if (data.job_id === appState.currentJobId && appState.isConverting) {
            updateConversionProgress(data.progress);
        }
    });
    appState.socket.on('conversion_complete', (data) => {
        if (data.job_id === appState.currentJobId) checkStatus();
    });
    appState.socket.on('conversion_error', (data) => {
        if (data.job_id === appState.currentJobId) checkStatus();
    });
}

const ui = {
    uploadZone: document.getElementById('uploadZone'),
    fileInput: document.getElementById('fileInput'),
    progressFill: document.getElementById('progressFill'),
    progressText: document.getElementById('progressText'),
    progressPercent: document.getElementById('progressPercent'),
    fileInfo: document.getElementById('fileInfo'),
    fileName: document.getElementById('fileName'),
    fileType: document.getElementById('fileType'),
    fileIcon: document.getElementById('fileIcon'),
    removeFile: document.getElementById('removeFile'),
    formatSelection: document.getElementById('formatSelection'),
    formatGrid: document.getElementById('formatGrid'),
    conversionProgress: document.getElementById('conversionProgress'),
    conversionPercentage: document.getElementById('conversionPercentage'),
    conversionFill: document.getElementById('conversionFill'),
    conversionStatus: document.getElementById('conversionStatus'),
    downloadSection: document.getElementById('downloadSection'),
    outputFilename: document.getElementById('outputFilename'),
    downloadBtn: document.getElementById('downloadBtn'),
    convertAnother: document.getElementById('convertAnother'),
    errorMessage: document.getElementById('errorMessage'),
    errorText: document.getElementById('errorText'),
    tryAgain: document.getElementById('tryAgain'),
    themeToggle: document.getElementById('themeToggle'),
    videoOptions: document.getElementById('videoOptions'),
    presetSelect: document.getElementById('presetSelect'),
    startVideoConversion: document.getElementById('startVideoConversion'),
    ocrOptions: document.getElementById('ocrOptions'),
    ocrSelect: document.getElementById('ocrSelect'),
    ocrEngineHint: document.getElementById('ocrEngineHint'),
    useLLM: document.getElementById('useLLM'),
    ocrCorrectHint: document.getElementById('ocrCorrectHint'),
    ocrThemeContainer: document.getElementById('ocrThemeContainer'),
    ocrThemeSelect: document.getElementById('ocrThemeSelect'),
    startOCRConversion: document.getElementById('startOCRConversion'),
    ocrCssContainer: document.getElementById('ocrCssContainer'),
    ocrLimitCss: document.getElementById('ocrLimitCss'),
    ocrCssSliderContainer: document.getElementById('ocrCssSliderContainer'),
    ocrCssLength: document.getElementById('ocrCssLength'),
    ocrCssValueDisplay: document.getElementById('ocrCssValueDisplay')
};

function isOcrFormat(format) {
    return (format || '').toLowerCase().startsWith('ocr-');
}

function formatLabel(format) {
    const lower = format.toLowerCase();
    if (lower.startsWith('ocr-')) return `OCR · ${lower.slice(4).toUpperCase()}`;
    if (lower === 'images') return t('pdf_fmt_images');
    if (lower === 'pdf_ocr') return t('pdf_fmt_ocr');
    return format.toUpperCase();
}

function updateOcrVisibility() {
    const engines = appState.ocrEngines || {};
    const engine = ui.ocrSelect.value;
    const correction = engines.correction || { available: false, reason: 'llm_offline' };
    const isHtml = (appState.selectedFormat || '').toLowerCase() === 'ocr-html';

    const hints = [];
    if (engine) hints.push(t(`ocr_engine_${engine}_desc`));
    ['rapid', 'qwen'].forEach(id => {
        const info = engines[id];
        if (info && !info.available) hints.push(`${t(`ocr_engine_${id}`)}: ${t(`ocr_reason_${info.reason}`, { model: info.model || '' })}`);
    });
    ui.ocrEngineHint.textContent = hints.join(' ');

    ui.useLLM.disabled = !correction.available;
    if (!correction.available) ui.useLLM.checked = false;
    ui.ocrCorrectHint.textContent = correction.available ? t('ocr_ai_correction_desc') : t(`ocr_reason_${correction.reason}`, { model: correction.model || '' });

    const llmHtml = isHtml && (engine === 'qwen' || ui.useLLM.checked);
    ui.ocrThemeContainer.classList.toggle('hidden', !isHtml);
    ui.ocrCssContainer.classList.toggle('hidden', !llmHtml);
    ui.ocrCssSliderContainer.classList.toggle('hidden', !llmHtml || !ui.ocrLimitCss.checked);
    ui.ocrCssValueDisplay.textContent = t('ocr_css_chars', { count: Number(ui.ocrCssLength.value) });
}

async function loadOcrEngines() {
    try {
        const res = await fetch('/api/ocr/engines');
        const body = await res.json();
        appState.ocrEngines = body.data || {};
    } catch (e) {
        appState.ocrEngines = { rapid: { available: true } };
    }
    const previous = ui.ocrSelect.value || 'rapid';
    ui.ocrSelect.innerHTML = ['rapid', 'qwen'].map(id => {
        const info = appState.ocrEngines[id] || { available: false };
        const label = t(`ocr_engine_${id}`) + (info.available ? '' : ` (${t('ocr_unavailable')})`);
        return `<option value="${id}" ${info.available ? '' : 'disabled'}>${escapeHtml(label)}</option>`;
    }).join('');
    ui.ocrSelect.value = appState.ocrEngines[previous]?.available ? previous : 'rapid';
    updateOcrVisibility();
}

function initEventListeners() {
    if (ui.removeFile) ui.removeFile.addEventListener('click', resetApp);
    if (ui.convertAnother) ui.convertAnother.addEventListener('click', resetApp);
    if (ui.tryAgain) ui.tryAgain.addEventListener('click', resetApp);
    if (ui.startVideoConversion) ui.startVideoConversion.addEventListener('click', () => startConversion(appState.selectedFormat));
    if (ui.startOCRConversion) ui.startOCRConversion.addEventListener('click', () => startConversion(appState.selectedFormat));

    if (ui.ocrSelect) {
        ui.ocrSelect.addEventListener('change', updateOcrVisibility);
        ui.useLLM.addEventListener('change', updateOcrVisibility);
        ui.ocrLimitCss.addEventListener('change', updateOcrVisibility);
        ui.ocrCssLength.addEventListener('input', updateOcrVisibility);
    }

    document.addEventListener('languagechange', () => {
        if (ui.ocrOptions && !ui.ocrOptions.classList.contains('hidden')) loadOcrEngines();
        if (appState.fileType) ui.fileType.textContent = t(`file_type_${appState.fileType}`);
        if (!ui.formatSelection.classList.contains('hidden')) {
            ui.formatGrid.querySelectorAll('.format-option').forEach(btn => { btn.textContent = formatLabel(btn.dataset.format); });
        }
        renderRecentHistory();
    });

    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'u') {
            e.preventDefault();
            switchMainTab('upload');
            ui.fileInput.click();
        }
        if (e.ctrlKey && e.key === 'Enter') {
            if (appState.currentFileId && !appState.isConverting && appState.selectedFormat) startConversion(appState.selectedFormat);
        }
        if (e.key === 'Escape') {
            const modal = document.getElementById('mobileModal');
            if (modal && !modal.classList.contains('hidden')) {
                modal.classList.add('hidden');
                return;
            }
            if (!appState.isConverting && appState.currentFileId) resetApp();
        }
    });

    document.addEventListener('paste', (e) => {
        if (document.activeElement.tagName === 'INPUT' || document.activeElement.tagName === 'TEXTAREA') return;
        const items = e.clipboardData?.items;
        if (!items) return;
        for (const item of items) {
            if (item.kind === 'file') {
                e.preventDefault();
                handleFileSelect(item.getAsFile());
                return;
            }
        }
    });
}

function initTheme() {
    const savedTheme = localStorage.getItem('theme-preference') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
}

function toggleTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme');
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', newTheme);
    localStorage.setItem('theme-preference', newTheme);
}

const api = {
    baseUrl: '/api',

    upload(file, onProgress) {
        return new Promise((resolve, reject) => {
            const formData = new FormData();
            formData.append('file', file);
            const xhr = new XMLHttpRequest();
            xhr.open('POST', `${this.baseUrl}/upload`);
            xhr.upload.addEventListener('progress', (e) => {
                if (e.lengthComputable && onProgress) onProgress(Math.round((e.loaded / e.total) * 100));
            });
            xhr.addEventListener('load', () => {
                try { resolve(JSON.parse(xhr.responseText)); }
                catch { reject({ key: xhr.status === 413 ? 'err_too_large' : 'err_upload_failed' }); }
            });
            xhr.addEventListener('error', () => reject({ key: 'err_upload_failed' }));
            xhr.addEventListener('abort', () => reject({ key: 'err_upload_failed' }));
            xhr.send(formData);
        });
    },

    async uploadUrl(url) {
        const response = await fetch(`${this.baseUrl}/upload-url`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        return response.json();
    },

    async startConversion(fileId, outputFormat, options = {}) {
        const response = await fetch(`${this.baseUrl}/convert`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ file_id: fileId, output_format: outputFormat, options })
        });
        return response.json();
    },

    async getStatus(jobId) {
        const response = await fetch(`${this.baseUrl}/status/${jobId}`);
        return response.json();
    },

    getDownloadUrl(jobId) {
        return `${this.baseUrl}/download/${jobId}`;
    }
};

function initUploadZone() {
    const zone = ui.uploadZone;
    const input = ui.fileInput;
    if (!zone || !input) return;

    ['dragenter', 'dragover'].forEach(event => {
        zone.addEventListener(event, (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.add('dragging');
        });
    });

    ['dragleave', 'drop'].forEach(event => {
        zone.addEventListener(event, (e) => {
            e.preventDefault();
            e.stopPropagation();
            zone.classList.remove('dragging');
        });
    });

    zone.addEventListener('drop', (e) => {
        const files = e.dataTransfer.files;
        if (files.length > 0) handleFileSelect(files[0]);
    });

    input.addEventListener('change', (e) => {
        if (e.target.files.length > 0) handleFileSelect(e.target.files[0]);
    });
}

function acceptUploadResult(data, filename) {
    appState.currentFileId = data.file_id;
    appState.fileType = data.file_type;
    appState.fileName = filename;
    appState.outputFormats = data.output_formats;
}

async function handleFileSelect(file) {
    ui.uploadZone.classList.add('uploading');
    updateProgress(0, 'uploading');

    try {
        const result = await api.upload(file, (pct) => updateProgress(pct, 'uploading'));
        updateProgress(100, 'uploading');
        if (!result.success) throw translateError(result.error, null, 'err_upload_failed');
        acceptUploadResult(result.data, file.name);

        setTimeout(() => {
            showFileInfo(file.name, result.data.file_type, file);
            showFormatSelection(result.data.output_formats);
            ui.uploadZone.classList.remove('uploading');
            ui.uploadZone.classList.add('hidden');
        }, 300);
    } catch (error) {
        ui.uploadZone.classList.remove('uploading');
        showError(error);
    }
}

function updateProgress(percentage, key) {
    ui.progressFill.style.width = `${Math.min(100, percentage)}%`;
    i18n.set(ui.progressText, key || 'uploading');
    ui.progressPercent.textContent = `${Math.round(percentage)}%`;
}

function showFileInfo(filename, fileType, file) {
    ui.fileName.textContent = filename;
    ui.fileType.textContent = t(`file_type_${fileType}`);
    ui.fileIcon.innerHTML = getFileTypeIcon(fileType);
    ui.fileInfo.classList.remove('hidden');
    ui.fileInfo.classList.add('animate-slide');

    const existing = ui.fileInfo.querySelector('.file-thumb');
    if (existing) existing.remove();

    if (file && fileType === 'image') {
        const thumb = document.createElement('img');
        thumb.className = 'file-thumb';
        thumb.src = URL.createObjectURL(file);
        thumb.alt = '';
        thumb.addEventListener('load', () => URL.revokeObjectURL(thumb.src));
        ui.fileInfo.querySelector('.file-details')?.prepend(thumb);
    } else if (file && fileType === 'video') {
        const video = document.createElement('video');
        video.src = URL.createObjectURL(file);
        video.muted = true;
        video.addEventListener('loadeddata', () => { video.currentTime = 1; });
        video.addEventListener('seeked', () => {
            const canvas = document.createElement('canvas');
            canvas.width = 48;
            canvas.height = 48;
            const ctx = canvas.getContext('2d');
            const scale = Math.max(48 / video.videoWidth, 48 / video.videoHeight);
            const w = video.videoWidth * scale;
            const h = video.videoHeight * scale;
            ctx.drawImage(video, (48 - w) / 2, (48 - h) / 2, w, h);
            const thumb = document.createElement('img');
            thumb.className = 'file-thumb';
            thumb.src = canvas.toDataURL();
            thumb.alt = '';
            ui.fileInfo.querySelector('.file-thumb')?.remove();
            ui.fileInfo.querySelector('.file-details')?.prepend(thumb);
            URL.revokeObjectURL(video.src);
        });
    }
}

function getFileTypeIcon(type) {
    const icons = {
        audio: `<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>`,
        video: `<svg viewBox="0 0 24 24"><polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/></svg>`,
        image: `<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>`,
        document: `<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>`
    };
    return icons[type] || icons.document;
}

function showFormatSelection(formats) {
    ui.formatGrid.innerHTML = '';
    const inputExtension = appState.fileName ? appState.fileName.split('.').pop().toLowerCase() : null;

    formats.filter(format => format.toLowerCase() !== inputExtension).forEach(format => {
        const btn = document.createElement('button');
        btn.className = 'format-option';
        btn.textContent = formatLabel(format);
        btn.dataset.format = format;
        btn.addEventListener('click', () => selectFormat(format, btn));
        ui.formatGrid.appendChild(btn);
    });
    ui.formatSelection.classList.remove('hidden');
    ui.formatSelection.classList.add('animate-slide');
}

async function selectFormat(format, button) {
    document.querySelectorAll('.format-option').forEach(btn => btn.classList.remove('active'));
    button.classList.add('active');
    appState.selectedFormat = format;

    if (ui.videoOptions) ui.videoOptions.classList.add('hidden');
    if (ui.ocrOptions) ui.ocrOptions.classList.add('hidden');

    const videoOutputFormats = ['mp4', 'webm', 'avi', 'mkv', 'mov'];

    if (appState.fileType === 'video' && videoOutputFormats.includes(format.toLowerCase())) {
        ui.videoOptions.classList.remove('hidden');
        ui.videoOptions.classList.add('animate-slide');
    } else if (isOcrFormat(format)) {
        ui.ocrOptions.classList.remove('hidden');
        ui.ocrOptions.classList.add('animate-slide');
        await loadOcrEngines();
    } else {
        setTimeout(() => startConversion(format), 300);
    }
}

async function startConversion(format) {
    if (appState.isConverting || !format) return;

    const options = {};
    if (appState.fileType === 'video' && !ui.videoOptions.classList.contains('hidden')) {
        options.preset = ui.presetSelect.value;
    }
    if (isOcrFormat(format) && !ui.ocrOptions.classList.contains('hidden')) {
        options.ocr_engine = ui.ocrSelect.value || 'rapid';
        options.use_llm = ui.useLLM.checked;
        if (!ui.ocrThemeContainer.classList.contains('hidden')) options.ocr_theme = ui.ocrThemeSelect.value;
        if (ui.ocrLimitCss.checked && !ui.ocrCssContainer.classList.contains('hidden')) {
            options.css_limit_enabled = true;
            options.css_limit_value = Number(ui.ocrCssLength.value);
        }
    }

    appState.isConverting = true;

    ui.formatSelection.classList.add('hidden');
    ui.fileInfo.classList.add('hidden');
    ui.videoOptions.classList.add('hidden');
    ui.ocrOptions.classList.add('hidden');
    ui.conversionProgress.classList.remove('hidden');
    ui.conversionProgress.classList.add('animate-scale');

    updateConversionProgress(0, 'conv_status_starting');

    try {
        const result = await api.startConversion(appState.currentFileId, format, options);
        if (!result.success) throw translateError(result.error, null, 'err_conversion_failed');
        appState.currentJobId = result.data.job_id;
        clearInterval(appState.pollInterval);
        appState.pollInterval = setInterval(checkStatus, 1500);
    } catch (error) {
        appState.isConverting = false;
        showError(error);
    }
}

async function checkStatus() {
    const jobId = appState.currentJobId;
    if (!jobId || !appState.isConverting) return;
    try {
        const result = await api.getStatus(jobId);
        if (jobId !== appState.currentJobId || !appState.isConverting) return;
        if (!result.success) throw translateError(result.error, null, 'err_file_missing');
        const data = result.data;
        updateConversionProgress(data.progress || 0);
        if (data.status === 'completed') {
            finishConversion();
            showDownloadSection(data.filename);
            Toast.success(t('complete'));
        } else if (data.status === 'failed' || data.status === 'cancelled') {
            finishConversion();
            showError(translateError({ message: data.error }, data.error_code, 'err_conversion_failed'));
        }
    } catch (error) {
        finishConversion();
        showError(error.key || error.message ? error : { key: 'err_connection' });
    }
}

function finishConversion() {
    appState.isConverting = false;
    clearInterval(appState.pollInterval);
    appState.pollInterval = null;
}

function updateConversionProgress(percentage, key) {
    ui.conversionPercentage.textContent = `${Math.round(percentage)}%`;
    ui.conversionFill.style.width = `${percentage}%`;
    i18n.set(ui.conversionStatus, key || getStatusKey(percentage));
}

function getStatusKey(progress) {
    if (progress < 15) return 'conv_status_preparing';
    if (progress < 40) return 'conv_status_processing';
    if (progress < 70) return 'conv_status_converting';
    if (progress < 90) return 'conv_status_finalizing';
    if (progress < 100) return 'conv_status_almost';
    return 'conv_status_complete';
}

function showDownloadSection(filename) {
    ui.conversionProgress.classList.add('hidden');
    ui.downloadSection.classList.remove('hidden');
    ui.downloadSection.classList.add('animate-scale');
    ui.outputFilename.textContent = filename;
    const jobId = appState.currentJobId;
    ui.downloadBtn.onclick = () => { window.location.href = api.getDownloadUrl(jobId); };

    saveToHistory(filename);
    OmniStats.recordJob(jobId, 'conversion', OmniStats.extOf(appState.fileName), (appState.selectedFormat || '').replace('ocr-', '') || OmniStats.extOf(filename));
}

function saveToHistory(outputFilename) {
    try {
        const history = JSON.parse(localStorage.getItem('omniconv_history') || '[]');
        const inputName = appState.fileName || '?';
        history.unshift({
            inputName,
            inputFormat: inputName.split('.').pop()?.toUpperCase() || '?',
            outputFormat: outputFilename.split('.').pop()?.toUpperCase() || '?',
            outputFilename,
            type: appState.fileType || 'document',
            timestamp: Date.now()
        });
        if (history.length > 50) history.length = 50;
        localStorage.setItem('omniconv_history', JSON.stringify(history));
        renderRecentHistory();
    } catch (e) {}
}

function showError(error) {
    ui.uploadZone.classList.add('hidden');
    ui.fileInfo.classList.add('hidden');
    ui.formatSelection.classList.add('hidden');
    ui.conversionProgress.classList.add('hidden');
    ui.downloadSection.classList.add('hidden');
    ui.videoOptions.classList.add('hidden');
    ui.ocrOptions.classList.add('hidden');
    if (error?.key) i18n.set(ui.errorText, error.key);
    else {
        delete ui.errorText.dataset.i18n;
        ui.errorText.textContent = error?.message || t('err_conversion_failed');
    }
    ui.errorMessage.classList.remove('hidden');
    ui.errorMessage.classList.add('animate-scale');
    Toast.error(ui.errorText.textContent);
}

function resetApp() {
    finishConversion();
    appState.currentFileId = null;
    appState.currentJobId = null;
    appState.fileType = null;
    appState.fileName = null;
    appState.outputFormats = [];
    appState.selectedFormat = null;

    ui.uploadZone.classList.remove('hidden', 'uploading');
    ui.fileInfo.classList.add('hidden');
    ui.formatSelection.classList.add('hidden');
    ui.conversionProgress.classList.add('hidden');
    ui.downloadSection.classList.add('hidden');
    ui.videoOptions.classList.add('hidden');
    ui.ocrOptions.classList.add('hidden');
    ui.useLLM.checked = false;
    ui.errorMessage.classList.add('hidden');
    ui.fileInput.value = '';
    ui.progressFill.style.width = '0%';
    ui.conversionFill.style.width = '0%';
    ui.fileInfo.querySelector('.file-thumb')?.remove();
}

function renderRecentHistory() {
    const container = document.getElementById('recentHistory');
    if (!container) return;

    let history = [];
    try { history = JSON.parse(localStorage.getItem('omniconv_history') || '[]'); } catch (e) {}
    if (!history.length) {
        container.innerHTML = '';
        return;
    }

    const typeIcons = {
        audio: '<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
        video: '<svg viewBox="0 0 24 24"><polygon points="23 7 16 12 23 17"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>',
        image: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
        document: '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>'
    };

    const rtf = new Intl.RelativeTimeFormat(i18n.currentLang, { numeric: 'auto' });
    const timeAgo = (ts) => {
        const minutes = Math.round((ts - Date.now()) / 60000);
        if (Math.abs(minutes) < 1) return t('just_now');
        if (Math.abs(minutes) < 60) return rtf.format(minutes, 'minute');
        if (Math.abs(minutes) < 1440) return rtf.format(Math.round(minutes / 60), 'hour');
        return rtf.format(Math.round(minutes / 1440), 'day');
    };

    container.innerHTML = `
        <h3 class="section-label" data-i18n="recent_conversions">${escapeHtml(t('recent_conversions'))}</h3>
        <div class="history-list">
            ${history.slice(0, 5).map(item => `
                <div class="history-item">
                    <div class="history-item-info">
                        <div class="history-item-icon">${typeIcons[item.type] || typeIcons.document}</div>
                        <span class="history-item-name">${escapeHtml(item.inputName)}</span>
                    </div>
                    <span class="history-item-badge">${escapeHtml(item.inputFormat)} → ${escapeHtml(item.outputFormat)}</span>
                    <span class="history-item-time">${escapeHtml(timeAgo(item.timestamp))}</span>
                </div>
            `).join('')}
        </div>
    `;
}

function init() {
    initTheme();
    if (ui.themeToggle) ui.themeToggle.addEventListener('click', toggleTheme);
    if (!ui.formatSelection) return;
    initUploadZone();
    initEventListeners();
    renderRecentHistory();
}

function switchMainTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('onclick').includes(tab));
    });

    const urlZone = document.getElementById('urlZone');
    if (tab === 'upload') {
        ui.uploadZone.classList.remove('hidden');
        ui.uploadZone.classList.add('tab-content');
        urlZone.classList.add('hidden');
    } else {
        ui.uploadZone.classList.add('hidden');
        urlZone.classList.remove('hidden');
        urlZone.classList.add('tab-content');
    }
}

async function submitUrl() {
    const urlInput = document.getElementById('urlInput');
    const url = urlInput.value.trim();
    if (!url) return;

    try {
        ui.uploadZone.classList.remove('hidden');
        document.getElementById('urlZone').classList.add('hidden');
        ui.uploadZone.classList.add('uploading');
        updateProgress(10, 'url_downloading');

        const result = await api.uploadUrl(url);
        updateProgress(100, 'url_downloading');
        if (!result.success) throw translateError(result.error, null, 'err_url_failed');
        acceptUploadResult(result.data, result.data.filename);

        setTimeout(() => {
            showFileInfo(result.data.filename, result.data.file_type);
            showFormatSelection(result.data.output_formats);
            ui.uploadZone.classList.remove('uploading');
            ui.uploadZone.classList.add('hidden');
        }, 400);
    } catch (error) {
        ui.uploadZone.classList.remove('uploading');
        showError(error);
    }
}

window.switchMainTab = switchMainTab;
window.submitUrl = submitUrl;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

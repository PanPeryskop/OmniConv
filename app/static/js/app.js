const appState = {
    currentFileId: null,
    currentJobId: null,
    fileType: null,
    fileName: null,
    outputFormats: [],
    selectedFormat: null,
    isConverting: false,
    pollInterval: null,
    socket: null
};

appState.socket = io();

appState.socket.on('conversion_progress', (data) => {
    if (data.job_id === appState.currentJobId) {
        updateConversionProgress(data.progress, getStatusMessage(data.progress));
    }
});

appState.socket.on('conversion_complete', (data) => {
    if (data.job_id === appState.currentJobId) {
        appState.isConverting = false;
        showDownloadSection(data.filename);
        Toast.success('Conversion complete!');
    }
});

appState.socket.on('conversion_error', (data) => {
    if (data.job_id === appState.currentJobId) {
        appState.isConverting = false;
        showError(data.error || 'Conversion failed');
        Toast.error(data.error || 'Conversion failed');
    }
});

const ui = {
    uploadZone: document.getElementById('uploadZone'),
    fileInput: document.getElementById('fileInput'),
    uploadProgress: document.getElementById('uploadProgress'),
    progressFill: document.getElementById('progressFill'),
    progressText: document.getElementById('progressText'),
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
    ocrThemeContainer: document.getElementById('ocrThemeContainer'),
    ocrThemeSelect: document.getElementById('ocrThemeSelect'),
    startOCRConversion: document.getElementById('startOCRConversion'),
    aiOptions: document.getElementById('aiOptions'),
    useLLM: document.getElementById('useLLM'),
    startAIConversion: document.getElementById('startAIConversion'),
    ocrCssContainer: document.getElementById('ocrCssContainer'),
    ocrLimitCss: document.getElementById('ocrLimitCss'),
    ocrCssSliderContainer: document.getElementById('ocrCssSliderContainer'),
    ocrCssLength: document.getElementById('ocrCssLength'),
    ocrCssValueDisplay: document.getElementById('ocrCssValueDisplay')
};

function initEventListeners() {
    if (ui.themeToggle) ui.themeToggle.addEventListener('click', toggleTheme);
    if (ui.removeFile) ui.removeFile.addEventListener('click', resetApp);
    if (ui.convertAnother) ui.convertAnother.addEventListener('click', resetApp);
    if (ui.tryAgain) ui.tryAgain.addEventListener('click', resetApp);
    if (ui.startVideoConversion) ui.startVideoConversion.addEventListener('click', confirmVideoConversion);
    if (ui.startOCRConversion) ui.startOCRConversion.addEventListener('click', confirmOCRConversion);
    if (ui.startAIConversion) ui.startAIConversion.addEventListener('click', () => startConversion(appState.selectedFormat));

    if (ui.ocrSelect) {
        const updateThemeVisibility = () => {
            const container = document.getElementById('ocrThemeContainer');
            const val = ui.ocrSelect.value;
            const isHtmlFormat = appState.selectedFormat && (appState.selectedFormat.toLowerCase() === 'html' || appState.selectedFormat.toLowerCase() === 'ocr-html');

            if (container) {
                const cssContainer = document.getElementById('ocrCssContainer');
                if ((val === 'qwen' || val === 'lighton_mistral') && isHtmlFormat) {
                    container.classList.remove('hidden');
                    if (cssContainer) cssContainer.classList.remove('hidden');
                } else {
                    container.classList.add('hidden');
                    if (cssContainer) cssContainer.classList.add('hidden');
                }
            }
        };

        ui.ocrSelect.addEventListener('change', updateThemeVisibility);

        if (ui.ocrLimitCss && ui.ocrCssLength && ui.ocrCssValueDisplay) {
            ui.ocrLimitCss.addEventListener('change', (e) => {
               if (e.target.checked) {
                   ui.ocrCssSliderContainer.classList.remove('hidden');
               } else {
                   ui.ocrCssSliderContainer.classList.add('hidden');
               }
            });

            ui.ocrCssLength.addEventListener('input', (e) => {
                ui.ocrCssValueDisplay.textContent = `Max ~${e.target.value} chars`;
            });
        }

        updateThemeVisibility();
    }

    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'u') {
            e.preventDefault();
            switchTab('upload');
            ui.fileInput.click();
        }
        if (e.ctrlKey && e.key === 'Enter') {
            if (appState.currentFileId && !appState.isConverting) {
                if (appState.selectedFormat) startConversion(appState.selectedFormat);
            }
        }
        if (e.key === 'Escape') {
            const chatWindow = document.getElementById('chat-window');
            if (chatWindow && chatWindow.classList.contains('open')) {
                chatWindow.classList.remove('open');
                return;
            }
            const modal = document.getElementById('mobileModal');
            if (modal && !modal.classList.contains('hidden')) {
                modal.classList.add('hidden');
                return;
            }
            if (appState.isConverting) {
                if (!ui.errorMessage.classList.contains('hidden')) resetApp();
                if (ui.videoOptions && !ui.videoOptions.classList.contains('hidden')) ui.videoOptions.classList.add('hidden');
                if (ui.aiOptions && !ui.aiOptions.classList.contains('hidden')) ui.aiOptions.classList.add('hidden');
            } else {
                if (appState.currentFileId) resetApp();
            }
        }
        if (e.key === 'd' && !e.ctrlKey && !e.metaKey && !e.altKey &&
            document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') {
            toggleTheme();
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
                if (e.lengthComputable && onProgress) {
                    onProgress(Math.round((e.loaded / e.total) * 100));
                }
            });
            xhr.addEventListener('load', () => {
                try { resolve(JSON.parse(xhr.responseText)); }
                catch { reject(new Error('Invalid response')); }
            });
            xhr.addEventListener('error', () => reject(new Error('Upload failed')));
            xhr.addEventListener('abort', () => reject(new Error('Upload aborted')));
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

    async getFormats(fileId) {
        const response = await fetch(`${this.baseUrl}/formats/${fileId}`);
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

async function handleFileSelect(file) {
    ui.uploadZone.classList.add('uploading');
    updateProgress(0);

    try {
        const result = await api.upload(file, (pct) => updateProgress(pct));

        updateProgress(100);

        if (!result.success) throw new Error(result.error?.message || 'Upload failed');

        appState.currentFileId = result.data.file_id;
        appState.fileType = result.data.file_type;
        appState.fileName = file.name;
        appState.outputFormats = result.data.output_formats;

        setTimeout(() => {
            showFileInfo(file.name, result.data.file_type, file);
            showFormatSelection(result.data.output_formats);
            ui.uploadZone.classList.remove('uploading');
            ui.uploadZone.classList.add('hidden');
        }, 300);

    } catch (error) {
        ui.uploadZone.classList.remove('uploading');
        showError(error.message);
        Toast.error(error.message);
    }
}

function updateProgress(percentage) {
    ui.progressFill.style.width = `${Math.min(100, percentage)}%`;
    ui.progressText.textContent = `Uploading... ${Math.round(percentage)}%`;
}

function showFileInfo(filename, fileType, file) {
    ui.fileName.textContent = filename;
    ui.fileType.textContent = fileType;
    ui.fileIcon.innerHTML = getFileTypeIcon(fileType);
    ui.fileInfo.classList.remove('hidden');
    ui.fileInfo.classList.add('animate-slide');

    if (file && fileType === 'image') {
        const thumb = document.createElement('img');
        thumb.className = 'file-thumb';
        thumb.src = URL.createObjectURL(file);
        thumb.alt = filename;
        thumb.addEventListener('load', () => URL.revokeObjectURL(thumb.src));
        const existing = ui.fileInfo.querySelector('.file-thumb');
        if (existing) existing.remove();
        ui.fileInfo.querySelector('.file-details')?.prepend(thumb);
    } else if (file && fileType === 'video') {
        const video = document.createElement('video');
        video.src = URL.createObjectURL(file);
        video.muted = true;
        video.addEventListener('loadeddata', () => {
            video.currentTime = 1;
        });
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
            thumb.alt = filename;
            const existing = ui.fileInfo.querySelector('.file-thumb');
            if (existing) existing.remove();
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

    const inputExtension = appState.fileName
        ? appState.fileName.split('.').pop().toLowerCase()
        : null;

    const filteredFormats = formats.filter(format =>
        format.toLowerCase() !== inputExtension
    );

    filteredFormats.forEach(format => {
        const btn = document.createElement('button');
        btn.className = 'format-option';
        btn.textContent = format.toUpperCase();
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
    if (ui.aiOptions) ui.aiOptions.classList.add('hidden');
    if (ui.ocrOptions) ui.ocrOptions.classList.add('hidden');

    const videoOutputFormats = ['mp4', 'webm', 'avi', 'mkv', 'mov'];
    const ocrPrefixedFormats = ['ocr-pdf', 'ocr-docx', 'ocr-md', 'ocr-txt', 'ocr-html'];
    const imageTextFormats = ['ocr-pdf', 'ocr-docx', 'ocr-md', 'ocr-txt', 'ocr-html'];

    if (appState.fileType === 'video' && videoOutputFormats.includes(format.toLowerCase())) {
        if (ui.videoOptions) {
            ui.videoOptions.classList.remove('hidden');
            ui.videoOptions.classList.add('animate-slide');
        }
    } else if (appState.fileType === 'image' && imageTextFormats.includes(format.toLowerCase())) {
        if (ui.ocrOptions) {
            ui.ocrOptions.classList.remove('hidden');
            ui.ocrOptions.classList.add('animate-slide');
            if (ui.ocrSelect) {
                const event = new Event('change');
                ui.ocrSelect.dispatchEvent(event);
            }
        }
    } else if (appState.fileType === 'document' && ocrPrefixedFormats.includes(format.toLowerCase())) {
        if (ui.ocrOptions) {
            ui.ocrOptions.classList.remove('hidden');
            ui.ocrOptions.classList.add('animate-slide');
            if (ui.ocrSelect) {
                const event = new Event('change');
                ui.ocrSelect.dispatchEvent(event);
            }
        }
    } else {
        setTimeout(() => startConversion(format), 300);
    }
}

function confirmVideoConversion() {
    startConversion(appState.selectedFormat);
}

function confirmOCRConversion() {
    startConversion(appState.selectedFormat);
}

async function startConversion(format) {
    if (appState.isConverting) return;

    const options = {};
    if (appState.fileType === 'video' && ui.presetSelect && ui.videoOptions && !ui.videoOptions.classList.contains('hidden')) {
        options.preset = ui.presetSelect.value;
    }
    if (ui.ocrSelect && ui.ocrOptions && !ui.ocrOptions.classList.contains('hidden')) {
        options.ocr_engine = ui.ocrSelect.value;
        if (ui.ocrThemeSelect && !ui.ocrThemeContainer.classList.contains('hidden')) {
            options.ocr_theme = ui.ocrThemeSelect.value;
        }
        if (ui.ocrLimitCss && ui.ocrLimitCss.checked && !ui.ocrCssContainer.classList.contains('hidden')) {
            options.css_limit_enabled = true;
            options.css_limit_value = ui.ocrCssLength.value;
        }
    }
    if (ui.useLLM && ui.useLLM.checked) {
        options.use_llm = true;
    }

    appState.isConverting = true;

    ui.formatSelection.classList.add('hidden');
    ui.fileInfo.classList.add('hidden');
    if (ui.videoOptions) ui.videoOptions.classList.add('hidden');
    if (ui.aiOptions) ui.aiOptions.classList.add('hidden');
    if (ui.ocrOptions) ui.ocrOptions.classList.add('hidden');
    ui.conversionProgress.classList.remove('hidden');
    ui.conversionProgress.classList.add('animate-scale');

    updateConversionProgress(0, 'Starting conversion...');

    try {
        const result = await api.startConversion(appState.currentFileId, format, options);
        if (!result.success) throw new Error(result.error?.message || 'Conversion failed to start');
        appState.currentJobId = result.data.job_id;
    } catch (error) {
        appState.isConverting = false;
        showError(error.message);
        Toast.error(error.message);
    }
}

function updateConversionProgress(percentage, statusText) {
    ui.conversionPercentage.textContent = `${Math.round(percentage)}%`;
    ui.conversionFill.style.width = `${percentage}%`;
    ui.conversionStatus.textContent = statusText;
}

function getStatusMessage(progress) {
    if (progress < 15) return 'Preparing file...';
    if (progress < 40) return 'Processing...';
    if (progress < 70) return 'Converting...';
    if (progress < 90) return 'Finalizing...';
    if (progress < 100) return 'Almost done...';
    return 'Complete!';
}

function showDownloadSection(filename) {
    ui.conversionProgress.classList.add('hidden');
    ui.downloadSection.classList.remove('hidden');
    ui.downloadSection.classList.add('animate-scale');
    ui.outputFilename.textContent = filename;
    ui.downloadBtn.onclick = () => { window.location.href = api.getDownloadUrl(appState.currentJobId); };

    saveToHistory(filename);
}

function saveToHistory(outputFilename) {
    try {
        const history = JSON.parse(localStorage.getItem('omniconv_history') || '[]');
        const inputName = appState.fileName || 'Unknown';
        const inputExt = inputName.split('.').pop()?.toUpperCase() || '?';
        const outputExt = outputFilename.split('.').pop()?.toUpperCase() || '?';

        history.unshift({
            inputName: inputName,
            inputFormat: inputExt,
            outputFormat: outputExt,
            outputFilename: outputFilename,
            type: appState.fileType || 'document',
            timestamp: Date.now()
        });

        const maxHistory = 50;
        if (history.length > maxHistory) history.length = maxHistory;

        localStorage.setItem('omniconv_history', JSON.stringify(history));
        renderRecentHistory();
    } catch (e) { /* noop */ }
}

function showError(message) {
    ui.uploadZone.classList.add('hidden');
    ui.fileInfo.classList.add('hidden');
    ui.formatSelection.classList.add('hidden');
    ui.conversionProgress.classList.add('hidden');
    ui.downloadSection.classList.add('hidden');
    ui.errorText.textContent = message;
    ui.errorMessage.classList.remove('hidden');
    ui.errorMessage.classList.add('animate-scale');
}

function resetApp() {
    appState.currentFileId = null;
    appState.currentJobId = null;
    appState.fileType = null;
    appState.fileName = null;
    appState.outputFormats = [];
    appState.selectedFormat = null;
    appState.isConverting = false;

    if (appState.pollInterval) {
        clearInterval(appState.pollInterval);
        appState.pollInterval = null;
    }

    ui.uploadZone.classList.remove('hidden', 'uploading');
    ui.fileInfo.classList.add('hidden');
    ui.formatSelection.classList.add('hidden');
    ui.conversionProgress.classList.add('hidden');
    ui.downloadSection.classList.add('hidden');
    if (ui.videoOptions) ui.videoOptions.classList.add('hidden');
    if (ui.aiOptions) ui.aiOptions.classList.add('hidden');
    if (ui.useLLM) ui.useLLM.checked = false;
    ui.errorMessage.classList.add('hidden');
    ui.fileInput.value = '';
    ui.progressFill.style.width = '0%';
    ui.conversionFill.style.width = '0%';

    const thumb = ui.fileInfo.querySelector('.file-thumb');
    if (thumb) thumb.remove();
}

function renderRecentHistory() {
    const container = document.getElementById('recentHistory');
    if (!container) return;

    const history = JSON.parse(localStorage.getItem('omniconv_history') || '[]');
    if (history.length === 0) {
        container.innerHTML = '';
        return;
    }

    const recent = history.slice(0, 5);
    const typeIcons = {
        audio: '<svg viewBox="0 0 24 24"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
        video: '<svg viewBox="0 0 24 24"><polygon points="23 7 16 12 23 17"/><rect x="1" y="5" width="15" height="14" rx="2"/></svg>',
        image: '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/></svg>',
        document: '<svg viewBox="0 0 24 24"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>'
    };

    const timeAgo = (ts) => {
        const diff = Date.now() - ts;
        if (diff < 60000) return 'just now';
        if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
        if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
        return `${Math.floor(diff / 86400000)}d ago`;
    };

    container.innerHTML = `
        <h3 class="section-label">Recent Conversions</h3>
        <div class="history-list">
            ${recent.map(item => `
                <div class="history-item">
                    <div class="history-item-info">
                        <div class="history-item-icon">${typeIcons[item.type] || typeIcons.document}</div>
                        <span class="history-item-name">${item.inputName}</span>
                    </div>
                    <span class="history-item-badge">${item.inputFormat} → ${item.outputFormat}</span>
                    <span class="history-item-time">${timeAgo(item.timestamp)}</span>
                </div>
            `).join('')}
        </div>
    `;
}

function init() {
    initTheme();
    initUploadZone();
    initEventListeners();
    renderRecentHistory();
}

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => {
        if (btn.getAttribute('onclick').includes(tab)) btn.classList.add('active');
    });

    if (tab === 'upload') {
        ui.uploadZone.classList.remove('hidden');
        ui.uploadZone.classList.add('tab-content');
        document.getElementById('urlZone').classList.add('hidden');
    } else {
        ui.uploadZone.classList.add('hidden');
        const urlZone = document.getElementById('urlZone');
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
        updateProgress(10, 'Downloading from URL...');

        const result = await api.uploadUrl(url);

        updateProgress(100);

        if (!result.success) throw new Error(result.error?.message || 'Download failed');

        appState.currentFileId = result.data.file_id;
        appState.fileType = result.data.file_type;
        appState.fileName = result.data.filename;
        appState.outputFormats = result.data.output_formats;

        setTimeout(() => {
            showFileInfo(result.data.filename, result.data.file_type);
            showFormatSelection(result.data.output_formats);
            ui.uploadZone.classList.remove('uploading');
            ui.uploadZone.classList.add('hidden');
        }, 400);

    } catch (error) {
        ui.uploadZone.classList.remove('uploading');
        showError(error.message);
        Toast.error(error.message);
    }
}

window.switchTab = switchTab;
window.submitUrl = submitUrl;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

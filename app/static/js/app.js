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

// Initialize Socket.IO
appState.socket = io();

appState.socket.on('connect', () => {
    console.log('Connected to WebSocket server');
});

appState.socket.on('conversion_progress', (data) => {
    if (data.job_id === appState.currentJobId) {
        updateConversionProgress(data.progress, getStatusMessage(data.progress));
    }
});

appState.socket.on('conversion_complete', (data) => {
    if (data.job_id === appState.currentJobId) {
        appState.isConverting = false;
        showDownloadSection(data.filename);
    }
});

appState.socket.on('conversion_error', (data) => {
    if (data.job_id === appState.currentJobId) {
        appState.isConverting = false;
        showError(data.error || 'Conversion failed');
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
    startVideoConversion: document.getElementById('startVideoConversion')
};

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
    
    async upload(file) {
        const formData = new FormData();
        formData.append('file', file);
        const response = await fetch(`${this.baseUrl}/upload`, { method: 'POST', body: formData });
        return response.json();
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
    
    if (!zone || !input) return; // Exit if elements don't exist
    
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
    const maxSize = 500 * 1024 * 1024;
    if (file.size > maxSize) {
        showError('File is too large. Maximum size is 500MB.');
        return;
    }
    
    ui.uploadZone.classList.add('uploading');
    updateProgress(0);
    
    try {
        const progressInterval = setInterval(() => {
            const currentWidth = parseFloat(ui.progressFill.style.width) || 0;
            if (currentWidth < 90) updateProgress(currentWidth + Math.random() * 15);
        }, 200);
        
        const result = await api.upload(file);
        
        clearInterval(progressInterval);
        updateProgress(100);
        
        if (!result.success) throw new Error(result.error?.message || 'Upload failed');
        
        appState.currentFileId = result.data.file_id;
        appState.fileType = result.data.file_type;
        appState.fileName = file.name;
        appState.outputFormats = result.data.output_formats;
        
        setTimeout(() => {
            showFileInfo(file.name, result.data.file_type);
            showFormatSelection(result.data.output_formats);
            ui.uploadZone.classList.remove('uploading');
            ui.uploadZone.classList.add('hidden');
        }, 400);
        
    } catch (error) {
        ui.uploadZone.classList.remove('uploading');
        showError(error.message);
    }
}

function updateProgress(percentage) {
    ui.progressFill.style.width = `${Math.min(100, percentage)}%`;
    ui.progressText.textContent = `Uploading... ${Math.round(percentage)}%`;
}

function showFileInfo(filename, fileType) {
    ui.fileName.textContent = filename;
    ui.fileType.textContent = fileType;
    ui.fileIcon.innerHTML = getFileTypeIcon(fileType);
    ui.fileInfo.classList.remove('hidden');
    ui.fileInfo.classList.add('animate-slide');
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
    
    // Show video options for video formats
    const videoOutputFormats = ['mp4', 'webm', 'avi', 'mkv', 'mov'];
    if (appState.fileType === 'video' && videoOutputFormats.includes(format.toLowerCase())) {
        if (ui.videoOptions) {
            ui.videoOptions.classList.remove('hidden');
            ui.videoOptions.classList.add('animate-slide');
        }
    } else {
        if (ui.videoOptions) ui.videoOptions.classList.add('hidden');
        setTimeout(() => startConversion(format), 300);
    }
}

function confirmVideoConversion() {
    startConversion(appState.selectedFormat);
}

async function startConversion(format) {
    if (appState.isConverting) return;
    appState.isConverting = true;
    
    ui.formatSelection.classList.add('hidden');
    ui.fileInfo.classList.add('hidden');
    if (ui.videoOptions) ui.videoOptions.classList.add('hidden');
    ui.conversionProgress.classList.remove('hidden');
    ui.conversionProgress.classList.add('animate-scale');
    
    updateConversionProgress(0, 'Starting conversion...');
    
    try {
        const options = {};
        if (appState.fileType === 'video' && ui.presetSelect) {
            options.preset = ui.presetSelect.value;
        }
        const result = await api.startConversion(appState.currentFileId, format, options);
        if (!result.success) throw new Error(result.error?.message || 'Conversion failed to start');
        appState.currentJobId = result.data.job_id;
        // WebSocket events will handle updates
    } catch (error) {
        appState.isConverting = false;
        showError(error.message);
    }
}

function pollConversionStatus() {
    // Deprecated in favor of WebSocket
    console.log('Polling deprecated');
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
    } catch (e) {
        console.error('Failed to save history:', e);
    }
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
    ui.errorMessage.classList.add('hidden');
    ui.fileInput.value = '';
    ui.progressFill.style.width = '0%';
    ui.conversionFill.style.width = '0%';
}

function initEventListeners() {
    if (ui.themeToggle) ui.themeToggle.addEventListener('click', toggleTheme);
    if (ui.removeFile) ui.removeFile.addEventListener('click', resetApp);
    if (ui.convertAnother) ui.convertAnother.addEventListener('click', resetApp);
    if (ui.tryAgain) ui.tryAgain.addEventListener('click', resetApp);
    if (ui.startVideoConversion) ui.startVideoConversion.addEventListener('click', confirmVideoConversion);
    
    // Keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.key === 'u') {
            e.preventDefault();
            switchTab('upload');
            ui.fileInput.click();
        }
        if (e.ctrlKey && e.key === 'Enter') {
            if (appState.currentFileId && !appState.isConverting) {
                // If format selected, convert. If not, maybe just log or hint.
                if (appState.selectedFormat) startConversion(appState.selectedFormat);
            }
        }
        if (e.key === 'Escape') {
            if (appState.isConverting) {
                // Cancel not implemented in backend fully (thread kill is hard), but we can reset UI
                // Only reset if error or modal
                if (!ui.errorMessage.classList.contains('hidden')) resetApp();
                if (!ui.videoOptions.classList.contains('hidden')) ui.videoOptions.classList.add('hidden');
            } else {
                if (appState.currentFileId) resetApp();
            }
        }
    });
}

function init() {
    initTheme();
    initUploadZone();
    initEventListeners();
}

function switchTab(tab) {
    document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(btn => {
        if (btn.getAttribute('onclick').includes(tab)) btn.classList.add('active');
    });

    if (tab === 'upload') {
        ui.uploadZone.classList.remove('hidden');
        document.getElementById('urlZone').classList.add('hidden');
    } else {
        ui.uploadZone.classList.add('hidden');
        document.getElementById('urlZone').classList.remove('hidden');
    }
}

async function submitUrl() {
    const urlInput = document.getElementById('urlInput');
    const url = urlInput.value.trim();
    if (!url) return;

    try {
        ui.uploadZone.classList.remove('hidden'); // Show progress in upload zone context
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
    }
}

// Make functions global for onclick
window.switchTab = switchTab;
window.submitUrl = submitUrl;

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

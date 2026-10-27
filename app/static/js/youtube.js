let selectedFormat = null;
let videoData = null;
let lastUrl = null;
let lastFormatId = null;
let lastIsPlaylist = false;
let pollTimer = null;
let currentJobId = null;

const YT_ERROR_CATEGORIES = ['auth', 'geo_blocked', 'age_restricted', 'rate_limited', 'private', 'not_found', 'network', 'unsupported', 'format_error'];
const YT_STATUS_KEYS = { 'Processing...': 'yt_status_processing' };

function setRawText(el, text) {
    delete el.dataset.i18n;
    delete el.dataset.i18nVars;
    el.textContent = text;
}

function setServerStatus(sData) {
    const el = document.getElementById('statusText');
    if (sData.status_text) {
        const key = YT_STATUS_KEYS[sData.status_text];
        if (key) i18n.set(el, key);
        else setRawText(el, sData.status_text);
    } else if (sData.status === 'downloading') {
        i18n.set(el, 'yt_status_downloading');
    } else if (sData.status === 'pending') {
        i18n.set(el, 'yt_status_waiting');
    }
}

function errorKeyFor(category) {
    return YT_ERROR_CATEGORIES.includes(category) ? `yt_err_${category}` : null;
}

const SUPPORTED_DOMAINS = [
    'youtube.com', 'youtu.be',
    'instagram.com', 'instagr.am',
    'tiktok.com', 'vm.tiktok.com',
    'twitter.com', 'x.com', 't.co',
    'vimeo.com',
    'facebook.com', 'fb.watch', 'fb.com',
    'reddit.com', 'redd.it',
    'twitch.tv', 'clips.twitch.tv',
    'dailymotion.com', 'dai.ly',
    'soundcloud.com',
    'threads.net',
    'pinterest.com', 'pin.it',
    'bilibili.com', 'b23.tv',
    'streamable.com',
    'rumble.com',
];

document.addEventListener('dragover', (e) => e.preventDefault());
document.addEventListener('drop', (e) => {
    e.preventDefault();
    const url = e.dataTransfer.getData('text') || e.dataTransfer.getData('text/uri-list');
    if(url && (url.startsWith('http://') || url.startsWith('https://'))) {
        document.getElementById('urlInput').value = url;
        fetchInfo();
    }
});

document.addEventListener('paste', (e) => {
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return;
    const paste = (e.clipboardData || window.clipboardData).getData('text');
    if (paste && (paste.startsWith('http://') || paste.startsWith('https://'))) {
        document.getElementById('urlInput').value = paste;
        fetchInfo();
    }
});

document.getElementById('urlInput').addEventListener('keypress', (e) => {
    if (e.key === 'Enter') fetchInfo();
});

function loadHistory() {
    const hist = JSON.parse(localStorage.getItem('omni_history') || '[]');
    const container = document.getElementById('recentHistoryContainer');
    if (!container) return;
    if (hist.length === 0) {
        container.innerHTML = '';
        return;
    }
    
    let html = `<h3 class="section-label" style="text-align: left; margin-top: var(--space-8);" data-i18n="yt_recent_downloads">${escapeHtml(t('yt_recent_downloads'))}</h3><div style="display: flex; flex-direction: column; gap: var(--space-2); margin-top: var(--space-3);">`;
    hist.forEach(item => {
        html += `<div class="panel" style="padding: var(--space-3); display: flex; justify-content: space-between; align-items: center; background: var(--bg-primary);">
            <div style="text-align: left; overflow: hidden;">
                <div style="font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 300px;">${escapeHtml(item.title)}</div>
                <div style="font-size: var(--text-xs); color: var(--text-muted);">${escapeHtml(item.date)} • ${escapeHtml(item.platform || 'URL')}</div>
            </div>
            <a class="btn btn-ghost" href="${escapeHtml(item.url)}" target="_blank" rel="noopener" style="padding: var(--space-2); min-width: auto;" data-i18n="yt_open">${escapeHtml(t('yt_open'))}</a>
        </div>`;
    });
    html += '</div>';
    container.innerHTML = html;
}

function addToHistory(title, url, platform) {
    let hist = JSON.parse(localStorage.getItem('omni_history') || '[]');
    hist.unshift({title, url, platform, date: new Date().toLocaleDateString()});
    if(hist.length > 5) hist.pop();
    localStorage.setItem('omni_history', JSON.stringify(hist));
    loadHistory();
}
document.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    const urlParams = new URLSearchParams(window.location.search);
    const passedUrl = urlParams.get('url');
    if (passedUrl) {
        const input = document.getElementById('urlInput');
        if (input) {
            input.value = passedUrl;
            fetchInfo();
        }
    }
});

async function quickMp3() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) {
        Toast.error(t('yt_enter_url'));
        return;
    }
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        Toast.error(t('yt_invalid_url'));
        return;
    }

    lastUrl = url;
    document.getElementById('inputSection').classList.add('hidden');
    document.getElementById('statusArea').classList.remove('hidden');
    i18n.set(document.getElementById('statusText'), 'yt_status_mp3');
    document.getElementById('speedText').textContent = '';
    document.getElementById('progressPercent').textContent = '0%';
    document.getElementById('progressCircle').style.strokeDashoffset = '339.292';

    selectedFormat = 'bestaudio/best';
    
    try {
        const response = await fetch('/api/youtube/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: url,
                format_id: selectedFormat,
                is_playlist: false,
                title: videoData?.title || '',
                label: 'mp3'
            })
        });

        const data = await response.json();
        if (!data.success) throw new Error(data.error || t('yt_failed'));

        const jobId = data.job_id;
        OmniJobs.refresh();
        currentJobId = jobId;
        const renameBtn = document.getElementById('smartRenameBtn');
        if (renameBtn) {
            renameBtn.style.display = 'inline-flex';
            renameBtn.disabled = false;
            renameBtn.innerHTML = `<svg viewBox="0 0 24 24" style="width: 18px; height: 18px; margin-right: 6px;"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" fill="none"/></svg> ${i18n.html('yt_ai_rename')}`;
        }
        let pollInterval = 1000;
        const maxPollInterval = 5000;
        const pollTimeout = 15 * 60 * 1000;
        const startTime = Date.now();

        function pollStatusQuick() {
            if (Date.now() - startTime > pollTimeout) {
                showYouTubeError(null, true, '', 'yt_err_timeout');
                return;
            }

            fetch(`/api/youtube/status/${jobId}`)
                .then(res => res.json())
                .then(sData => {
                    if (sData.progress !== undefined) {
                        const pct = Math.round(sData.progress);
                        document.getElementById('progressPercent').textContent = `${pct}%`;
                        const circle = document.getElementById('progressCircle');
                        circle.style.strokeDashoffset = 339.292 * (1 - pct / 100);
                    }

                    setServerStatus(sData);

                    const speedParts = [];
                    if (sData.speed) speedParts.push(formatSpeed(sData.speed));
                    if (sData.eta) speedParts.push(formatETA(sData.eta));
                    document.getElementById('speedText').textContent = speedParts.join(' · ');

                    if (sData.status === 'completed') {
                        document.getElementById('statusArea').classList.add('hidden');
                        document.getElementById('resultSection').classList.remove('hidden');
                        document.getElementById('resultFilename').textContent = sData.filename || '';
                        document.getElementById('resultDownloadBtn').href = `/api/youtube/download-file/${jobId}`;
                        Toast.success(t('yt_complete'));
                        addToHistory(sData.filename || 'Audio', url, 'MP3');
                        return;
                    }

                    if (sData.status === 'error') {
                        showYouTubeError(sData.error, true, sData.category);
                        return;
                    }

                    if (sData.progress > 0 && sData.progress < 95) pollInterval = 1000;
                    else pollInterval = Math.min(pollInterval + 500, maxPollInterval);
                    
                    pollTimer = setTimeout(pollStatusQuick, pollInterval);
                })
                .catch(err => {
                    pollInterval = Math.min(pollInterval * 2, maxPollInterval);
                    pollTimer = setTimeout(pollStatusQuick, pollInterval);
                });
        }
        pollTimer = setTimeout(pollStatusQuick, pollInterval);

    } catch (error) {
        showYouTubeError(error.message, true);
    }
}

async function fetchInfo() {
    const url = document.getElementById('urlInput').value.trim();
    if (!url) return;
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        Toast.error(t('yt_invalid_url'));
        return;
    }

    lastUrl = url;
    const fetchBtn = document.getElementById('fetchBtn');
    fetchBtn.disabled = true;
    fetchBtn.innerHTML = i18n.html('yt_loading');

    try {
        const response = await fetch('/api/youtube/info', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const data = await response.json();
        if (!data.success) {
            const key = errorKeyFor(data.category);
            throw new Error(key ? t(key) : (data.error || t('yt_info_failed')));
        }

        videoData = data;

        const thumbEl = document.getElementById('thumbnail');
        if (data.thumbnail) {
            thumbEl.src = data.thumbnail;
            thumbEl.style.display = '';
        } else {
            thumbEl.style.display = 'none';
        }

        const titleEl = document.getElementById('videoTitle');
        if (data.title) setRawText(titleEl, data.title);
        else i18n.set(titleEl, 'yt_unknown_title');
        document.getElementById('videoUploader').textContent = data.uploader || '';
        document.getElementById('videoDuration').textContent = data.duration ? formatDuration(data.duration) : '';

        const badge = document.getElementById('platformBadge');
        if (data.platform && data.platform !== 'other') {
            badge.textContent = data.platform;
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }

        if (data.is_playlist) {
            document.getElementById('playlistInfo').classList.remove('hidden');
            const playlistCount = data.playlist_count || data.entries?.length;
            const countEl = document.getElementById('playlistCount');
            if (playlistCount) i18n.set(countEl, 'yt_playlist_count', { count: playlistCount });
            else i18n.set(countEl, 'yt_playlist_count_unknown');
            selectedFormat = 'best';
            document.getElementById('downloadBtn').disabled = false;
        } else {
            document.getElementById('playlistInfo').classList.add('hidden');
            renderFormats(data.formats);
        }

        document.getElementById('inputSection').classList.add('hidden');
        document.getElementById('videoInfo').classList.remove('hidden');
        Toast.info(t('yt_info_loaded'));

    } catch (error) {
        Toast.error(error.message);
    } finally {
        fetchBtn.disabled = false;
        fetchBtn.innerHTML = `
            <svg viewBox="0 0 24 24" style="width: 18px; height: 18px;">
                <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" stroke="currentColor" stroke-width="2" stroke-linecap="round" fill="none"/>
            </svg>
            ${i18n.html('yt_get_info')}
        `;
    }
}

function formatDuration(seconds) {
    if (!seconds || isNaN(seconds)) return '';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${m}:${String(s).padStart(2, '0')}`;
}

function formatSpeed(bytesPerSec) {
    if (!bytesPerSec) return '';
    if (bytesPerSec > 1048576) return `${(bytesPerSec / 1048576).toFixed(1)} MB/s`;
    if (bytesPerSec > 1024) return `${(bytesPerSec / 1024).toFixed(0)} KB/s`;
    return `${bytesPerSec} B/s`;
}

function formatETA(seconds) {
    if (!seconds || isNaN(seconds)) return '';
    let time;
    if (seconds < 60) time = `${Math.ceil(seconds)}s`;
    else if (seconds < 3600) time = `${Math.ceil(seconds / 60)} min`;
    else time = `${Math.floor(seconds / 3600)}h ${Math.ceil((seconds % 3600) / 60)} min`;
    return t('yt_remaining', { time });
}

function renderFormats(formats) {
    const container = document.getElementById('formatOptions');
    container.innerHTML = '';

    if (!formats || formats.length === 0) {
        selectedFormat = 'best';
        document.getElementById('downloadBtn').disabled = false;
        container.innerHTML = `<div class="format-option active" data-i18n="yt_best_quality">${escapeHtml(t('yt_best_quality'))}</div>`;
        return;
    }

    const seen = new Set();
    formats.forEach((f, index) => {
        const label = f.resolution || f.note || f.ext || t('yt_unknown_format');
        if (seen.has(label)) return;
        seen.add(label);

        const btn = document.createElement('button');
        btn.className = 'format-option';

        let text = label;
        if (f.filesize) {
            const sizeMB = (f.filesize / 1048576).toFixed(1);
            text += ` (${sizeMB} MB)`;
        }
        btn.textContent = text;

        btn.addEventListener('click', () => {
            document.querySelectorAll('#formatOptions .format-option').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            selectedFormat = f.format_id || 'best';
            document.getElementById('downloadBtn').disabled = false;
        });

        if (index === 0) {
            btn.classList.add('active');
            selectedFormat = f.format_id || 'best';
            document.getElementById('downloadBtn').disabled = false;
        }

        container.appendChild(btn);
    });
}

async function startDownload() {
    if (!selectedFormat) return;

    document.getElementById('videoInfo').classList.add('hidden');
    document.getElementById('statusArea').classList.remove('hidden');
    i18n.set(document.getElementById('statusText'), 'yt_status_starting');
    document.getElementById('speedText').textContent = '';
    document.getElementById('progressPercent').textContent = '0%';
    document.getElementById('progressCircle').style.strokeDashoffset = '339.292';

    const isPlaylist = document.getElementById('playlistCheckbox')?.checked && videoData?.is_playlist;
    lastFormatId = selectedFormat;
    lastIsPlaylist = isPlaylist;

    try {
        const response = await fetch('/api/youtube/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                url: document.getElementById('urlInput').value.trim(),
                format_id: selectedFormat,
                is_playlist: isPlaylist,
                title: videoData?.title || '',
                label: videoData?.formats?.find(f => f.format_id === selectedFormat)?.resolution || ''
            })
        });

        const data = await response.json();
        if (!data.success) throw new Error(data.error || t('yt_failed'));

        const jobId = data.job_id;
        OmniJobs.refresh();
        currentJobId = jobId;
        const renameBtn = document.getElementById('smartRenameBtn');
        if (renameBtn) {
            renameBtn.style.display = 'inline-flex';
            renameBtn.disabled = false;
            renameBtn.innerHTML = `<svg viewBox="0 0 24 24" style="width: 18px; height: 18px; margin-right: 6px;"><path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3L12 3Z" stroke="currentColor" stroke-width="2" stroke-linejoin="round" fill="none"/></svg> ${i18n.html('yt_ai_rename')}`;
        }
        let pollInterval = 1000;
        const maxPollInterval = 5000;
        const pollTimeout = 15 * 60 * 1000;
        const startTime = Date.now();

        function pollStatus() {
            if (Date.now() - startTime > pollTimeout) {
                showYouTubeError(null, true, '', 'yt_err_timeout_long');
                return;
            }

            fetch(`/api/youtube/status/${jobId}`)
                .then(res => res.json())
                .then(sData => {
                    if (sData.progress !== undefined) {
                        const pct = Math.round(sData.progress);
                        document.getElementById('progressPercent').textContent = `${pct}%`;
                        const circle = document.getElementById('progressCircle');
                        circle.style.strokeDashoffset = 339.292 * (1 - pct / 100);
                    }

                    setServerStatus(sData);

                    const speedParts = [];
                    if (sData.speed) speedParts.push(formatSpeed(sData.speed));
                    if (sData.eta) speedParts.push(formatETA(sData.eta));
                    document.getElementById('speedText').textContent = speedParts.join(' · ');

                    if (sData.status === 'completed') {
                        document.getElementById('statusArea').classList.add('hidden');
                        document.getElementById('resultSection').classList.remove('hidden');
                        document.getElementById('resultFilename').textContent = sData.filename || '';
                        document.getElementById('resultDownloadBtn').href = `/api/youtube/download-file/${jobId}`;
                        Toast.success(t('yt_complete'));
                        if(videoData) {
                             addToHistory(videoData.title, lastUrl, videoData.platform);
                        }
                        return;
                    }

                    if (sData.status === 'error') {
                        const retryPossible = sData.retry_possible !== false;
                        showYouTubeError(sData.error, retryPossible, sData.category);
                        return;
                    }

                    if (sData.progress > 0 && sData.progress < 95) {
                        pollInterval = 1000;
                    } else {
                        pollInterval = Math.min(pollInterval + 500, maxPollInterval);
                    }
                    pollTimer = setTimeout(pollStatus, pollInterval);
                })
                .catch(err => {
                    pollInterval = Math.min(pollInterval * 2, maxPollInterval);
                    pollTimer = setTimeout(pollStatus, pollInterval);
                });
        }

        pollTimer = setTimeout(pollStatus, pollInterval);

    } catch (error) {
        showYouTubeError(error.message, true);
    }
}

function showYouTubeError(message, retryPossible = true, category = '', key = null) {
    if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
    }

    document.getElementById('statusArea').classList.add('hidden');
    document.getElementById('videoInfo').classList.add('hidden');
    document.getElementById('errorSection').classList.remove('hidden');
    const errorEl = document.getElementById('errorText');
    const errorKey = key || errorKeyFor(category);
    if (errorKey) i18n.set(errorEl, errorKey);
    else if (message) setRawText(errorEl, message);
    else i18n.set(errorEl, 'yt_failed');

    const retryBtn = document.getElementById('retryBtn');
    retryBtn.style.display = retryPossible ? '' : 'none';

    const hintEl = document.getElementById('errorHint');
    if (category === 'auth') {
        i18n.set(hintEl, 'yt_hint_auth');
        hintEl.style.display = '';
    } else if (category === 'rate_limited') {
        i18n.set(hintEl, 'yt_hint_rate_limited');
        hintEl.style.display = '';
    } else {
        hintEl.style.display = 'none';
    }

    Toast.error(errorEl.textContent);
}

function retryDownload() {
    if (!lastUrl) {
        resetYouTube();
        return;
    }
    document.getElementById('errorSection').classList.add('hidden');
    document.getElementById('statusArea').classList.remove('hidden');

    startDownload();
}

function resetYouTube() {
    if (pollTimer) {
        clearTimeout(pollTimer);
        pollTimer = null;
    }
    selectedFormat = null;
    videoData = null;
    lastUrl = null;
    lastFormatId = null;
    lastIsPlaylist = false;
    document.getElementById('urlInput').value = '';
    document.getElementById('inputSection').classList.remove('hidden');
    document.getElementById('videoInfo').classList.add('hidden');
    document.getElementById('statusArea').classList.add('hidden');
    document.getElementById('resultSection').classList.add('hidden');
    document.getElementById('errorSection').classList.add('hidden');
    document.getElementById('downloadBtn').disabled = true;
    document.getElementById('progressPercent').textContent = '0%';
    document.getElementById('progressCircle').style.strokeDashoffset = '339.292';
    document.getElementById('speedText').textContent = '';
}

async function smartRename() {
    if (!currentJobId) return;
    const btn = document.getElementById('smartRenameBtn');
    btn.disabled = true;
    const oldText = btn.innerHTML;
    btn.innerHTML = i18n.html('yt_thinking');
    
    try {
        const response = await fetch(`/api/youtube/smart-rename/${currentJobId}`, { method: 'POST' });
        const data = await response.json();
        if(data.success && data.new_name) {
            setRawText(document.getElementById('resultFilename'), data.new_name);
            document.getElementById('resultDownloadBtn').href = `/api/youtube/download-file/${currentJobId}`;
            Toast.success(t('yt_renamed'));
            btn.style.display = 'none';
        } else {
            throw new Error(data.error || t('yt_rename_failed'));
        }
    } catch(err) {
        Toast.error(err.message);
        btn.innerHTML = oldText;
        btn.disabled = false;
    }
}

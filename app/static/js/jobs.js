const OmniJobs = (() => {
    const ACTIVE_POLL_MS = 1500;
    const IDLE_POLL_MS = 30000;
    const state = { jobs: [], retentionHours: 24, serverOffset: 0, loaded: false };
    const listeners = [];
    let timer = null;
    let inFlight = false;

    const ICONS = {
        convert: '<path d="m17 2 4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="m7 22-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
        compress: '<path d="m15 15 6 6"/><path d="m15 9 6-6"/><path d="M21 16v5h-5"/><path d="M21 8V3h-5"/><path d="M3 16v5h5"/><path d="m3 21 6-6"/><path d="M3 8V3h5"/><path d="M9 9 3 3"/>',
        pdf: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
        video: '<path d="m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"/><rect x="2" y="6" width="14" height="12" rx="2"/>'
    };
    const ACTION_ICONS = {
        download: '<path d="M12 15V3"/><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/>',
        cancel: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
        remove: '<path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/>'
    };

    function svg(paths) {
        return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
    }

    function running() {
        return state.jobs.filter(job => job.status === 'running');
    }

    async function load() {
        const res = await fetch('/api/jobs', { cache: 'no-store' });
        const body = await res.json();
        if (!body.success) throw new Error('jobs');
        state.jobs = body.data.jobs || [];
        state.retentionHours = body.data.retention_hours || 24;
        state.serverOffset = body.data.server_time * 1000 - Date.now();
        state.loaded = true;
    }

    function schedule() {
        clearTimeout(timer);
        timer = setTimeout(tick, running().length ? ACTIVE_POLL_MS : IDLE_POLL_MS);
    }

    async function tick() {
        if (inFlight) return;
        if (document.hidden && state.loaded) {
            schedule();
            return;
        }
        inFlight = true;
        try {
            await load();
            updateNavBadge();
            listeners.forEach(fn => fn(state));
        } catch (e) {
        } finally {
            inFlight = false;
            schedule();
        }
    }

    function refresh() {
        clearTimeout(timer);
        return tick();
    }

    function subscribe(fn) {
        listeners.push(fn);
        if (state.loaded) fn(state);
    }

    function updateNavBadge() {
        const link = document.querySelector('a.nav-link[href="/dashboard"]');
        if (!link) return;
        let badge = link.querySelector('.nav-badge');
        const count = running().length;
        if (!count) {
            badge?.remove();
            return;
        }
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'nav-badge';
            link.appendChild(badge);
        }
        badge.textContent = String(count);
        badge.title = t('jobs_running_count', { count });
    }

    async function remove(id) {
        const res = await fetch(`/api/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' });
        const body = await res.json().catch(() => ({}));
        await refresh();
        return body;
    }

    async function clearFinished() {
        await fetch('/api/jobs', { method: 'DELETE' });
        await refresh();
    }

    function formatBytes(bytes) {
        if (!bytes) return '';
        if (bytes < 1024) return `${bytes} B`;
        if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)} KB`;
        if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
        return `${(bytes / 1073741824).toFixed(2)} GB`;
    }

    function relative(targetSeconds) {
        const diff = targetSeconds * 1000 - (Date.now() + state.serverOffset);
        const abs = Math.abs(diff);
        const rtf = new Intl.RelativeTimeFormat(i18n.currentLang, { numeric: 'auto' });
        if (abs < 3600000) return rtf.format(Math.round(diff / 60000), 'minute');
        if (abs < 86400000) return rtf.format(Math.round(diff / 3600000), 'hour');
        return rtf.format(Math.round(diff / 86400000), 'day');
    }

    function formatName(value) {
        const v = String(value || '').toLowerCase();
        if (v.startsWith('ocr-')) return `${v.slice(4).toUpperCase()} (OCR)`;
        if (v === 'pdf_ocr') return 'PDF (OCR)';
        if (v === 'images') return t('jobs_format_images');
        return v.toUpperCase();
    }

    function describe(job) {
        if (job.kind === 'convert') return `${formatName(job.src)} → ${formatName(job.dst)}`;
        if (job.kind === 'compress') return `${formatName(job.src)} · ${t('activity_compression')}`;
        if (job.kind === 'pdf') return `PDF · ${t(`pdf_tool_${job.dst}`, job.dst)}`;
        const playlist = job.dst.startsWith('playlist:');
        const label = playlist ? job.dst.slice(9) : job.dst;
        const quality = label === 'best' ? t('jobs_best_quality') : label === 'mp3' ? 'MP3' : label;
        return [job.src, playlist ? t('jobs_playlist') : null, quality].filter(Boolean).join(' · ');
    }

    function statusText(job) {
        if (job.status === 'running') {
            return job.progress > 0 ? `${Math.floor(job.progress)}%` : t('jobs_status_running');
        }
        if (job.status === 'completed') {
            if (!job.file_available) return t('jobs_file_missing');
            return [formatBytes(job.output_size), t('jobs_expires', { time: relative(job.expires_at) })].filter(Boolean).join(' · ');
        }
        if (job.status === 'cancelled') return t('jobs_status_cancelled');
        const fallback = job.error || t('jobs_status_failed');
        return job.error_code && job.error_code.startsWith('err_') ? t(job.error_code, fallback) : fallback;
    }

    function actions(job) {
        const out = [];
        if (job.status === 'completed' && job.file_available) {
            out.push(`<a class="job-action primary" href="/api/jobs/${encodeURIComponent(job.id)}/download" title="${escapeHtml(t('jobs_download'))}" aria-label="${escapeHtml(t('jobs_download'))}">${svg(ACTION_ICONS.download)}</a>`);
        }
        if (job.status === 'running' && job.kind !== 'video') {
            out.push(`<button type="button" class="job-action" data-action="cancel" data-id="${escapeHtml(job.id)}" title="${escapeHtml(t('jobs_cancel'))}" aria-label="${escapeHtml(t('jobs_cancel'))}">${svg(ACTION_ICONS.cancel)}</button>`);
        }
        if (job.status !== 'running') {
            out.push(`<button type="button" class="job-action" data-action="remove" data-id="${escapeHtml(job.id)}" title="${escapeHtml(t('jobs_remove'))}" aria-label="${escapeHtml(t('jobs_remove'))}">${svg(ACTION_ICONS.remove)}</button>`);
        }
        return out.join('');
    }

    function renderItem(job) {
        const progress = job.status === 'running'
            ? `<div class="progress-track job-progress"><div class="progress-bar" style="width: ${Math.max(3, Math.min(100, job.progress || 0))}%"></div></div>`
            : '';
        return `
            <div class="job-row is-${escapeHtml(job.status)}">
                <div class="job-icon">${svg(ICONS[job.kind] || ICONS.convert)}</div>
                <div class="job-main">
                    <div class="job-title" title="${escapeHtml(job.title)}">${escapeHtml(job.title)}</div>
                    <div class="job-meta"><span>${escapeHtml(describe(job))}</span><span class="job-status">${escapeHtml(statusText(job))}</span></div>
                    ${progress}
                </div>
                <div class="job-actions">${actions(job)}</div>
            </div>`;
    }

    function mount(root) {
        const list = root.querySelector('[data-jobs-list]');
        const empty = root.querySelector('[data-jobs-empty]');
        const note = root.querySelector('[data-jobs-note]');
        const clear = root.querySelector('[data-jobs-clear]');

        function render() {
            const jobs = state.jobs;
            list.innerHTML = jobs.map(renderItem).join('');
            empty.classList.toggle('hidden', jobs.length > 0);
            clear.classList.toggle('hidden', !jobs.some(job => job.status !== 'running'));
            const hours = Math.round(state.retentionHours);
            note.textContent = t('jobs_note', { hours });
        }

        list.addEventListener('click', async (e) => {
            const button = e.target.closest('button[data-action]');
            if (!button) return;
            button.disabled = true;
            const body = await remove(button.dataset.id);
            if (body && body.success === false) Toast.error(t(body.error?.code || 'jobs_status_failed', body.error?.message));
        });
        clear.addEventListener('click', () => clearFinished());
        document.addEventListener('languagechange', render);
        subscribe(render);
    }

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) refresh();
    });
    document.addEventListener('DOMContentLoaded', () => {
        document.querySelectorAll('[data-jobs-panel]').forEach(mount);
        refresh();
    });

    return { refresh, subscribe, remove, clearFinished };
})();

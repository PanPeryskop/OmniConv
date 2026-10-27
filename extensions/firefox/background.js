const JOBS_KEY = "jobs";
const MAX_FINISHED = 60;
const POLL_MS = 1500;
const POLL_ALARM = "omniconv-poll";
const MAX_MISSES = 20;

let writeChain = Promise.resolve();
let pollTimer = null;
let polling = false;

async function readJobs() {
    const { jobs } = await browser.storage.local.get(JOBS_KEY);
    return jobs || [];
}

function trimJobs(jobs) {
    let finished = 0;
    return jobs.filter(j => OC.isActive(j) || finished++ < MAX_FINISHED);
}

function mutateJobs(fn) {
    const next = writeChain.then(async () => {
        const jobs = await readJobs();
        const result = fn(jobs);
        await browser.storage.local.set({ [JOBS_KEY]: trimJobs(jobs) });
        return result;
    });
    writeChain = next.catch(() => {});
    return next;
}

async function getJob(id) {
    return (await readJobs()).find(j => j.id === id) || null;
}

async function addJob(job) {
    const now = Date.now();
    const full = { id: OC.uid(), status: "starting", progress: 0, createdAt: now, updatedAt: now, ...job };
    await mutateJobs(jobs => { jobs.unshift(full); });
    refreshBadge();
    return full;
}

async function patchJob(id, patch) {
    const job = await mutateJobs(jobs => {
        const j = jobs.find(x => x.id === id);
        if (!j) return null;
        Object.assign(j, patch, { updatedAt: Date.now() });
        return { ...j };
    });
    refreshBadge();
    return job;
}

async function transitionJob(id, from, patch) {
    const job = await mutateJobs(jobs => {
        const j = jobs.find(x => x.id === id);
        if (!j || !from.includes(j.status)) return null;
        Object.assign(j, patch, { updatedAt: Date.now() });
        return { ...j };
    });
    if (job) refreshBadge();
    return job;
}

async function refreshBadge() {
    try {
        const jobs = await readJobs();
        const active = jobs.filter(OC.isActive);
        const { unseenError } = await browser.storage.local.get("unseenError");
        let text = "";
        let color = "#8b5cf6";
        if (active.length === 1 && active[0].status === "processing" && active[0].progress > 0) {
            text = `${Math.floor(active[0].progress)}%`;
        } else if (active.length) {
            text = String(active.length);
        } else if (unseenError) {
            text = "!";
            color = "#ef4444";
        }
        await browser.action.setBadgeBackgroundColor({ color });
        if (browser.action.setBadgeTextColor) await browser.action.setBadgeTextColor({ color: "#ffffff" });
        await browser.action.setBadgeText({ text });
    } catch {
        return;
    }
}

async function notify(id, title, message) {
    const settings = await OC.getSettings();
    if (!settings.notifications) return;
    try {
        await browser.notifications.create(`oc:${id}`, { type: "basic", title, message: message || "" });
    } catch {
        return;
    }
}

function notifyStart(job) {
    notify(job.id, OC.t("ntfStartTitle"), [job.title, job.formatLabel].filter(Boolean).join(" · "));
}

async function failJob(id, error) {
    if (error && error.userCancelled) {
        await patchJob(id, { status: "cancelled", statusText: "", error: null });
        return;
    }
    const message = (error && error.message) || String(error || OC.t("errUnknown"));
    const job = await patchJob(id, {
        status: "error",
        error: message,
        retryable: !(error && error.retryable === false),
        saveFailed: !!(error && error.saveFailed),
        statusText: ""
    });
    await browser.storage.local.set({ unseenError: true });
    refreshBadge();
    if (job) notify(id, OC.t("ntfErrorTitle"), `${job.title}\n${message}`);
}

async function startMedia({ url, formatId, formatLabel, isPlaylist, title, thumbnail, source }) {
    const job = await addJob({
        kind: "media",
        title: title || url,
        titleIsUrl: !title,
        url,
        thumbnail: thumbnail || null,
        formatLabel,
        isPlaylist: !!isPlaylist,
        statusText: OC.t("stStarting"),
        payload: { url, formatId, isPlaylist: !!isPlaylist }
    });
    if (source !== "popup") notifyStart(job);
    runMedia(job.id);
    return job;
}

async function runMedia(id) {
    const job = await getJob(id);
    if (!job) return;
    const { url, formatId, isPlaylist } = job.payload;
    try {
        const data = await OC.api("/api/youtube/download", {
            method: "POST",
            json: { url, format_id: formatId, is_playlist: isPlaylist }
        });
        await transitionJob(id, ["starting"], { status: "processing", serverJobId: data.job_id, statusText: OC.t("stQueued"), misses: 0 });
        schedulePoll(0);
    } catch (e) {
        const current = await getJob(id);
        if (current && current.status === "starting") await failJob(id, e);
    }
}

async function startConvert({ sourceUrl, target, kind, title, source }) {
    const ocr = kind === "ocr";
    const job = await addJob({
        kind: ocr ? "ocr" : "convert",
        title: title || OC.filenameFromUrl(sourceUrl) || OC.t("lblFile"),
        url: sourceUrl,
        thumbnail: null,
        formatLabel: ocr ? OC.t("fmtOcrText") : OC.targetLabel(target),
        statusText: OC.t("stUploading"),
        payload: { sourceUrl, target: ocr ? null : String(target).toLowerCase() }
    });
    if (source !== "popup") notifyStart(job);
    runConvert(job.id);
    return job;
}

async function uploadFromUrl(sourceUrl) {
    let blob;
    let name;
    try {
        const res = await fetch(sourceUrl, { credentials: "include" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        blob = await res.blob();
        name = OC.filenameFor(sourceUrl, res.headers.get("content-disposition"), blob.type);
    } catch {
        if (OC.isWebUrl(sourceUrl)) {
            const r = await OC.api("/api/upload-url", { method: "POST", json: { url: sourceUrl }, timeout: 600000 });
            return r.data;
        }
        throw new OC.ApiError(OC.t("errFetchSource"), { retryable: true });
    }
    const form = new FormData();
    form.append("file", blob, name);
    const r = await OC.api("/api/upload", { method: "POST", body: form, timeout: 600000 });
    return r.data;
}

async function copyText(text) {
    if (!text) return false;
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch {
        return false;
    }
}

async function runConvert(id) {
    const job = await getJob(id);
    if (!job) return;
    const { sourceUrl, target } = job.payload;
    try {
        const uploaded = await uploadFromUrl(sourceUrl);
        if (uploaded.filename) await patchJob(id, { title: uploaded.filename });

        if (job.kind === "ocr") {
            await patchJob(id, { statusText: OC.t("stOcr") });
            const settings = await OC.getSettings();
            const res = await OC.api("/api/ocr", {
                method: "POST",
                json: { file_id: uploaded.file_id, lang: settings.ocrLang },
                timeout: 600000
            });
            const text = ((res.data && res.data.text) || "").trim();
            if (!text) throw new OC.ApiError(OC.t("errOcrEmpty"), { retryable: false });
            const copied = await copyText(text);
            const done = await transitionJob(id, ["starting"], {
                status: "done",
                progress: 100,
                text,
                statusText: copied ? OC.t("stCopied") : OC.t("stOcrReady")
            });
            if (done) notify(id, OC.t("ntfOcrTitle"), copied ? OC.t("ntfOcrCopied") : text.slice(0, 140));
            return;
        }

        const formats = (uploaded.output_formats || []).map(f => String(f).toLowerCase());
        if (!formats.includes(target)) {
            throw new OC.ApiError(
                OC.t("errFormatUnavailable", [OC.targetLabel(target), formats.map(OC.targetLabel).join(", ") || "—"]),
                { retryable: false }
            );
        }
        const res = await OC.api("/api/convert", {
            method: "POST",
            json: { file_id: uploaded.file_id, output_format: target }
        });
        await transitionJob(id, ["starting"], {
            status: "processing",
            serverJobId: res.data.job_id,
            statusText: OC.t("stConverting"),
            misses: 0
        });
        schedulePoll(0);
    } catch (e) {
        const current = await getJob(id);
        if (current && current.status === "starting") await failJob(id, e);
    }
}

function schedulePoll(delay = POLL_MS) {
    if (pollTimer) clearTimeout(pollTimer);
    pollTimer = setTimeout(pollOnce, delay);
}

async function pollOnce() {
    pollTimer = null;
    if (polling) return;
    polling = true;
    let pending = false;
    try {
        const jobs = (await readJobs()).filter(j => j.status === "processing" && j.serverJobId);
        pending = jobs.length > 0;
        if (pending) {
            browser.alarms.create(POLL_ALARM, { periodInMinutes: 0.5 });
            await Promise.all(jobs.map(pollJob));
        } else {
            browser.alarms.clear(POLL_ALARM);
        }
    } finally {
        polling = false;
    }
    if (pending) schedulePoll();
}

async function pollJob(job) {
    try {
        if (job.kind === "media") {
            const s = await OC.api(`/api/youtube/status/${job.serverJobId}`, { timeout: 10000 });
            if (s.status === "error") {
                return failJob(job.id, new OC.ApiError(s.error || OC.t("errUnknown"), { retryable: s.retry_possible !== false }));
            }
            if (s.status === "completed") return completeJob(job.id, s.filename);
            await transitionJob(job.id, ["processing"], {
                progress: s.progress || 0,
                speed: s.speed || null,
                eta: s.eta != null ? s.eta : null,
                statusText: s.status_text || (s.status === "pending" ? OC.t("stQueued") : OC.t("stDownloading")),
                misses: 0
            });
            return;
        }
        const r = await OC.api(`/api/status/${job.serverJobId}`, { timeout: 10000 });
        const s = r.data || {};
        if (s.status === "failed") return failJob(job.id, new OC.ApiError(s.error || OC.t("errUnknown"), { retryable: true }));
        if (s.status === "cancelled") return transitionJob(job.id, ["processing"], { status: "cancelled", statusText: "" });
        if (s.status === "completed") {
            return completeJob(job.id, s.filename, { inputSize: s.input_size || null, outputSize: s.output_size || null });
        }
        await transitionJob(job.id, ["processing"], { progress: s.progress || 0, statusText: OC.t("stConverting"), misses: 0 });
    } catch (e) {
        if (e.status === 404) return failJob(job.id, new OC.ApiError(OC.t("errJobLost"), { retryable: true }));
        const misses = (job.misses || 0) + 1;
        if (misses >= MAX_MISSES) return failJob(job.id, e);
        await transitionJob(job.id, ["processing"], { misses, statusText: OC.t("stReconnecting") });
    }
}

async function completeJob(id, serverFilename, extra = {}) {
    const job = await transitionJob(id, ["processing"], {
        status: "saving",
        progress: 100,
        speed: null,
        eta: null,
        statusText: OC.t("stSaving"),
        ...extra
    });
    if (!job) return;
    const settings = await OC.getSettings();
    let name = serverFilename || "download";
    if (job.kind === "media" && settings.smartRename && !job.isPlaylist) {
        try {
            await patchJob(id, { statusText: OC.t("stRenaming") });
            const r = await OC.api(`/api/youtube/smart-rename/${job.serverJobId}`, { method: "POST", timeout: 60000 });
            if (r.new_name) name = r.new_name;
        } catch {
            name = serverFilename || name;
        }
    }
    if (job.kind !== "media") name = OC.stripJobSuffix(name);
    const safe = OC.sanitizeFilename(name);
    const folder = OC.sanitizeFolder(settings.subfolder);
    const base = OC.normalizeServer(settings.serverUrl);
    const path = job.kind === "media" ? `/api/youtube/download-file/${job.serverJobId}` : `/api/download/${job.serverJobId}`;
    const patch = { filename: safe, statusText: OC.t("stSaving") };
    if (job.titleIsUrl) {
        patch.title = safe.replace(/\.[^.]+$/, "");
        patch.titleIsUrl = false;
    }
    await patchJob(id, patch);
    try {
        const downloadId = await browser.downloads.download({
            url: base + path,
            filename: folder ? `${folder}/${safe}` : safe,
            saveAs: !!settings.saveAs,
            conflictAction: "uniquify"
        });
        await patchJob(id, { downloadId });
        const [item] = await browser.downloads.search({ id: downloadId });
        if (item && item.state === "complete") await finishDownload(id, item);
        if (item && item.state === "interrupted") await failDownload(id, item.error);
    } catch (e) {
        const cancelled = /cancel/i.test((e && e.message) || "");
        await failJob(id, new OC.ApiError((e && e.message) || OC.t("errSave"), { saveFailed: true, retryable: true, userCancelled: cancelled }));
    }
}

async function finishDownload(id, item) {
    const job = await transitionJob(id, ["saving"], {
        status: "done",
        statusText: "",
        outputSize: (item && (item.fileSize || item.totalBytes)) || null,
        localPath: (item && item.filename) || null
    });
    if (job) notify(id, OC.t("ntfDoneTitle"), job.filename || job.title);
}

async function failDownload(id, reason) {
    if (reason === "USER_CANCELED") {
        await transitionJob(id, ["saving"], { status: "cancelled", statusText: "" });
        return;
    }
    const job = await getJob(id);
    if (job && job.status === "saving") {
        await failJob(id, new OC.ApiError(OC.t("errDownloadInterrupted", [reason || "?"]), { saveFailed: true, retryable: true }));
    }
}

browser.downloads.onChanged.addListener(async delta => {
    if (!delta.state) return;
    const job = (await readJobs()).find(j => j.downloadId === delta.id);
    if (!job) return;
    if (delta.state.current === "complete") {
        const [item] = await browser.downloads.search({ id: delta.id });
        await finishDownload(job.id, item);
    } else if (delta.state.current === "interrupted") {
        const [item] = await browser.downloads.search({ id: delta.id });
        await failDownload(job.id, item && item.error);
    }
});

async function retryJob(id) {
    const job = await getJob(id);
    if (!job || OC.isActive(job)) return;
    if (job.saveFailed && job.serverJobId) {
        await patchJob(id, { status: "processing", error: null, saveFailed: false, statusText: OC.t("stSaving"), misses: 0 });
        schedulePoll(0);
        return;
    }
    await patchJob(id, {
        status: "starting",
        progress: 0,
        error: null,
        saveFailed: false,
        serverJobId: null,
        downloadId: null,
        speed: null,
        eta: null,
        statusText: job.kind === "media" ? OC.t("stStarting") : OC.t("stUploading")
    });
    if (job.kind === "media") runMedia(id);
    else runConvert(id);
}

async function cancelJob(id) {
    const job = await getJob(id);
    if (!job || !OC.isActive(job)) return;
    if (job.status === "saving" && job.downloadId != null) {
        try {
            await browser.downloads.cancel(job.downloadId);
        } catch {
            job.downloadId = null;
        }
    }
    if (job.kind !== "media" && job.serverJobId && job.status === "processing") {
        OC.api(`/api/cancel/${job.serverJobId}`, { method: "POST", timeout: 5000 }).catch(() => {});
    }
    await patchJob(id, { status: "cancelled", statusText: "", speed: null, eta: null });
}

async function removeJob(id) {
    await mutateJobs(jobs => {
        const i = jobs.findIndex(j => j.id === id);
        if (i >= 0 && !OC.isActive(jobs[i])) jobs.splice(i, 1);
    });
    refreshBadge();
}

async function clearFinished() {
    await mutateJobs(jobs => {
        const keep = jobs.filter(OC.isActive);
        jobs.splice(0, jobs.length, ...keep);
    });
    await browser.storage.local.set({ unseenError: false });
    refreshBadge();
}

async function markSeen() {
    await browser.storage.local.set({ unseenError: false });
    refreshBadge();
}

async function openApp(url) {
    const base = OC.normalizeServer((await OC.getSettings()).serverUrl);
    const target = OC.isWebUrl(url) && !url.startsWith(base) ? `${base}/youtube?url=${encodeURIComponent(OC.singleVideoUrl(url))}` : `${base}/`;
    await browser.tabs.create({ url: target });
}

async function notifyError(message) {
    const settings = await OC.getSettings();
    if (!settings.notifications) return;
    browser.notifications.create({ type: "basic", title: OC.t("ntfErrorTitle"), message });
}

function mediaUrlFromInfo(info) {
    return [info.linkUrl, info.srcUrl, info.pageUrl].find(OC.isWebUrl) || null;
}

async function setupMenus() {
    await browser.contextMenus.removeAll();
    const mk = props => browser.contextMenus.create(props);
    const media = ["link", "video", "audio", "page"];
    mk({ id: "dl-best", title: OC.t("menuDownloadBest"), contexts: media });
    mk({ id: "dl-audio", title: OC.t("menuDownloadAudio"), contexts: media });
    mk({ id: "dl-quality", title: OC.t("menuDownloadQuality"), contexts: media });
    for (const q of ["2160", "1440", "1080", "720", "480"]) {
        mk({ id: `dl-q-${q}`, parentId: "dl-quality", title: `${q}p`, contexts: media });
    }
    mk({ id: "sep-convert", type: "separator", contexts: ["image", "link"] });
    mk({ id: "img-convert", title: OC.t("menuConvertImage"), contexts: ["image"] });
    for (const f of OC.TARGETS.image) {
        mk({ id: `img-to-${f}`, parentId: "img-convert", title: OC.targetLabel(f), contexts: ["image"] });
    }
    mk({ id: "img-ocr", title: OC.t("menuOcr"), contexts: ["image"] });
    mk({ id: "link-convert", title: OC.t("menuConvertLink"), contexts: ["link"] });
    for (const f of OC.LINK_TARGETS) {
        mk({ id: `link-to-${f}`, parentId: "link-convert", title: OC.targetLabel(f), contexts: ["link"] });
    }
    mk({ id: "sep-app", type: "separator", contexts: ["page", "link", "image", "video", "audio"] });
    mk({ id: "open-app", title: OC.t("menuOpenApp"), contexts: ["page", "link", "image", "video", "audio", "action"] });
    mk({ id: "open-queue", title: OC.t("menuOpenQueue"), contexts: ["action"] });
}

browser.contextMenus.onClicked.addListener(async (info, tab) => {
    const id = String(info.menuItemId);
    if (id === "open-app") return openApp(info.pageUrl || (tab && tab.url));
    if (id === "open-queue") return browser.action.openPopup().catch(() => {});
    if (id.startsWith("dl-")) {
        const raw = mediaUrlFromInfo(info);
        if (!raw) return notifyError(OC.t("errNoUrl"));
        const url = OC.singleVideoUrl(raw);
        const preset = id === "dl-best" ? (await OC.getSettings()).defaultQuality : id === "dl-audio" ? "audio" : id.slice(5);
        const fmt = OC.presetFormat(preset);
        const title = tab && OC.singleVideoUrl(tab.url) === url ? tab.title : null;
        return startMedia({ url, formatId: fmt.formatId, formatLabel: fmt.formatLabel, title, source: "menu" });
    }
    if (id.startsWith("img-to-")) return startConvert({ sourceUrl: info.srcUrl, target: id.slice(7), source: "menu" });
    if (id === "img-ocr") return startConvert({ sourceUrl: info.srcUrl, kind: "ocr", source: "menu" });
    if (id.startsWith("link-to-")) return startConvert({ sourceUrl: info.linkUrl, target: id.slice(8), source: "menu" });
});

browser.commands.onCommand.addListener(async (command, tab) => {
    if (command !== "quick-download" && command !== "quick-audio") return;
    const active = tab || (await browser.tabs.query({ active: true, currentWindow: true }))[0];
    if (!active || !OC.isWebUrl(active.url)) return notifyError(OC.t("errNoUrl"));
    const settings = await OC.getSettings();
    const fmt = OC.presetFormat(command === "quick-audio" ? "audio" : settings.defaultQuality);
    startMedia({
        url: OC.singleVideoUrl(active.url),
        formatId: fmt.formatId,
        formatLabel: fmt.formatLabel,
        title: active.title,
        source: "command"
    });
});

browser.notifications.onClicked.addListener(async notificationId => {
    if (!notificationId.startsWith("oc:")) return;
    browser.notifications.clear(notificationId);
    const job = await getJob(notificationId.slice(3));
    if (job && job.downloadId != null && job.status === "done") {
        browser.downloads.show(job.downloadId).catch(() => {});
    }
});

browser.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === POLL_ALARM) schedulePoll(0);
});

browser.runtime.onMessage.addListener(msg => {
    switch (msg && msg.type) {
        case "start-media": return startMedia({ ...msg.payload, source: "popup" }).then(j => j.id);
        case "start-convert": return startConvert({ ...msg.payload, source: "popup" }).then(j => j.id);
        case "retry": return retryJob(msg.id);
        case "cancel": return cancelJob(msg.id);
        case "remove": return removeJob(msg.id);
        case "clear-finished": return clearFinished();
        case "seen": return markSeen();
        case "open-app": return openApp(msg.url);
        default: return undefined;
    }
});

browser.runtime.onInstalled.addListener(details => {
    setupMenus();
    if (details.reason === "install") browser.runtime.openOptionsPage();
});

browser.runtime.onStartup.addListener(setupMenus);

async function recoverJobs() {
    const jobs = await readJobs();
    for (const job of jobs) {
        if (job.status === "starting") {
            await failJob(job.id, new OC.ApiError(OC.t("errInterrupted"), { retryable: true }));
        } else if (job.status === "saving") {
            if (job.downloadId == null) {
                await patchJob(job.id, { status: "processing" });
                continue;
            }
            const [item] = await browser.downloads.search({ id: job.downloadId });
            if (!item) await failDownload(job.id, "MISSING");
            else if (item.state === "complete") await finishDownload(job.id, item);
            else if (item.state === "interrupted") await failDownload(job.id, item.error);
        }
    }
    refreshBadge();
    schedulePoll(0);
}

recoverJobs();

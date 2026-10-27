const $ = id => document.getElementById(id);
const { h, icon } = UI;
const INFO_TTL = 10 * 60 * 1000;

const state = {
    tab: { url: "", title: "" },
    url: "",
    settings: null,
    view: null,
    yt: null,
    ytMode: "video",
    info: null,
    chips: [],
    selected: null,
    userPicked: false,
    loadToken: 0,
    mediaLoaded: false,
    fileType: null,
    fileName: "",
    fileExt: "",
    targets: [],
    target: null,
    highlight: null
};

function send(type, extra = {}) {
    return browser.runtime.sendMessage({ type, ...extra });
}

function hostOf(url) {
    try {
        return new URL(url).hostname.replace(/^www\./, "");
    } catch {
        return "";
    }
}

function ytThumb(url) {
    const m = /[?&]v=([\w-]{6,})/.exec(url || "");
    return m ? `https://i.ytimg.com/vi/${m[1]}/hqdefault.jpg` : null;
}

function setTab(name) {
    state.view = name;
    document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === name));
    for (const v of ["media", "file", "queue"]) $(`view-${v}`).hidden = v !== name;
    if (name === "media" && !state.mediaLoaded) {
        state.mediaLoaded = true;
        setupMedia();
    }
}

async function checkServer() {
    const el = $("status");
    el.className = "status checking";
    $("statusText").textContent = OC.t("statusChecking");
    const ok = await OC.ping();
    el.className = `status ${ok ? "online" : "offline"}`;
    $("statusText").textContent = OC.t(ok ? "statusOnline" : "statusOffline");
    return ok;
}

function currentMediaUrl() {
    if (state.yt) return state.ytMode === "playlist" ? state.yt.playlist : state.yt.video || state.url;
    return state.url;
}

function isPlaylistMode() {
    return state.info ? !!state.info.is_playlist : state.ytMode === "playlist";
}

function presetChips() {
    const keys = ["best", "1080", "720", "480", "audio"];
    const pref = state.settings.defaultQuality;
    if (/^\d+$/.test(pref) && !keys.includes(pref)) keys.splice(1, 0, pref);
    return keys.map(key => {
        const f = OC.presetFormat(key);
        const audio = key === "audio";
        const best = key === "best";
        return {
            label: f.formatLabel,
            formatId: f.formatId,
            sub: audio ? "MP3" : best ? OC.t("chipBestSub") : OC.t("chipMaxSub"),
            audio,
            best,
            height: +key || 0
        };
    });
}

function serverChips(formats) {
    const seen = new Set();
    const out = [];
    for (const f of formats) {
        const label = OC.serverFormatLabel(f);
        if (seen.has(label)) continue;
        seen.add(label);
        const audio = f.format_id === "bestaudio/best";
        const best = f.format_id === "bestvideo+bestaudio/best" || f.format_id === "best";
        const sub = audio
            ? "MP3"
            : best
                ? OC.t("chipBestSub")
                : [OC.formatBytes(f.filesize), (f.ext || "").toUpperCase()].filter(Boolean).join(" · ");
        out.push({ label, formatId: f.format_id || "best", sub, audio, best, height: OC.labelHeight(label) });
    }
    if (!out.some(c => c.audio)) out.push(presetChips().find(c => c.audio));
    return out;
}

function pickChip(chips) {
    if (state.userPicked && state.selected) {
        const same = chips.find(c => c.label === state.selected.label);
        if (same) return same;
    }
    const pref = state.settings.defaultQuality;
    if (pref === "audio") return chips.find(c => c.audio) || chips[0];
    if (/^\d+$/.test(pref)) {
        const fit = chips.filter(c => c.height && c.height <= +pref).sort((a, b) => b.height - a.height)[0];
        if (fit) return fit;
    }
    return chips.find(c => c.best) || chips[0];
}

function renderChips() {
    $("formatChips").replaceChildren(...state.chips.map(c => h("button", {
        type: "button",
        class: `chip${c === state.selected ? " selected" : ""}`,
        title: c.formatId,
        onclick: () => {
            state.selected = c;
            state.userPicked = true;
            renderChips();
        }
    },
    h("span", { class: "chip-label" }, c.audio ? icon("music", 13) : c.best ? icon("zap", 13) : null, c.label),
    h("span", { class: "chip-sub", text: c.sub || " " }))));
    updateDownloadLabel();
}

function updateDownloadLabel() {
    const label = state.selected ? state.selected.label : "";
    $("downloadLabel").textContent = OC.t(isPlaylistMode() ? "btnDownloadPlaylist" : "btnDownload", [label]);
}

function setThumb(src) {
    const img = $("thumbImg");
    const fallback = () => {
        img.hidden = true;
        $("noThumb").hidden = false;
    };
    if (!src) return fallback();
    img.onerror = fallback;
    img.hidden = false;
    $("noThumb").hidden = true;
    if (img.getAttribute("src") !== src) img.src = src;
}

function showOffline() {
    $("mediaMain").hidden = true;
    $("mediaEmpty").hidden = true;
    $("mediaOffline").hidden = false;
    $("offlineUrl").textContent = OC.normalizeServer(state.settings.serverUrl);
}

function setupMedia() {
    if (!OC.isWebUrl(state.url)) {
        $("mediaEmpty").hidden = false;
        return;
    }
    state.yt = OC.youtubeParts(state.url);
    const both = state.yt && state.yt.video && state.yt.playlist;
    if (state.yt && !state.yt.video && state.yt.playlist) state.ytMode = "playlist";
    $("ytSwitch").hidden = !both;
    syncSwitch();
    loadInfo(false);
    showShortcutHint();
}

function syncSwitch() {
    document.querySelectorAll("#ytSwitch button").forEach(b => b.classList.toggle("active", b.dataset.mode === state.ytMode));
}

async function loadInfo(force) {
    const url = currentMediaUrl();
    const token = ++state.loadToken;
    const playlist = state.ytMode === "playlist";
    const provisionalThumb = playlist ? null : ytThumb(url);
    const knownTitle = !playlist && state.tab.title ? state.tab.title : "";

    state.info = null;
    $("mediaOffline").hidden = true;
    $("mediaEmpty").hidden = true;
    $("mediaMain").hidden = false;
    $("infoError").hidden = true;
    $("playlistBox").hidden = true;
    $("durationBadge").hidden = true;
    $("platformBadge").hidden = true;
    $("mediaCard").className = ["card", "loading", provisionalThumb && "has-thumb", knownTitle && "title-known"].filter(Boolean).join(" ");
    setThumb(provisionalThumb);
    $("mediaTitle").textContent = knownTitle || " ";
    $("mediaSub").textContent = " ";

    state.chips = presetChips();
    state.selected = pickChip(state.chips);
    renderChips();

    try {
        let info = force ? null : await OC.cacheGet(`info:${url}`, INFO_TTL);
        if (!info) {
            info = await OC.api("/api/youtube/info", { method: "POST", json: { url }, timeout: 120000 });
            OC.cacheSet(`info:${url}`, info).catch(() => {});
        }
        if (token !== state.loadToken) return;
        state.info = info;
        renderInfo(info, url);
    } catch (e) {
        if (token !== state.loadToken) return;
        $("mediaCard").className = "card";
        if (!provisionalThumb) setThumb(null);
        if (e.offline) return showOffline();
        $("mediaTitle").textContent = knownTitle || state.tab.title || url;
        $("mediaSub").textContent = hostOf(url);
        $("infoErrorText").textContent = e.message || OC.t("errUnknown");
        $("infoError").hidden = false;
    }
}

function renderInfo(info, url) {
    $("mediaCard").className = "card";
    setThumb(info.thumbnail || ytThumb(url));
    $("mediaTitle").textContent = info.title || state.tab.title || url;
    const count = info.playlist_count || (info.entries || []).length;
    $("mediaSub").textContent = [info.uploader, info.is_playlist ? OC.t("lblItems", [String(count)]) : null]
        .filter(Boolean).join(" · ") || hostOf(url);

    const duration = OC.formatDuration(info.duration);
    $("durationBadge").hidden = !duration;
    $("durationBadge").textContent = duration;
    const platform = info.platform && info.platform !== "other" ? info.platform : "";
    $("platformBadge").hidden = !platform;
    $("platformBadge").textContent = platform;

    if (info.is_playlist) {
        const entries = (info.entries || []).slice(0, 100);
        $("plHead").textContent = OC.t("lblPlaylistItems", [String(count)]);
        $("plList").replaceChildren(...entries.map(e => h("li", {},
            h("span", { text: e.title || e.id || "—" }),
            e.duration ? ` · ${OC.formatDuration(e.duration)}` : null)));
        $("playlistBox").hidden = entries.length === 0;
        state.chips = presetChips();
    } else {
        state.chips = info.formats && info.formats.length ? serverChips(info.formats) : presetChips();
    }
    state.selected = pickChip(state.chips);
    renderChips();
}

function flashButton(btn, labelEl, key, restore) {
    btn.classList.add("success");
    labelEl.textContent = OC.t(key);
    setTimeout(() => {
        btn.classList.remove("success");
        restore();
    }, 1100);
}

async function startDownload() {
    if (!state.selected) return;
    const btn = $("downloadBtn");
    btn.disabled = true;
    const url = currentMediaUrl();
    const info = state.info;
    const playlist = isPlaylistMode();
    try {
        const id = await send("start-media", {
            payload: {
                url,
                formatId: state.selected.formatId,
                formatLabel: state.selected.label,
                isPlaylist: playlist,
                title: (info && info.title) || (!playlist && state.tab.title) || null,
                thumbnail: (info && info.thumbnail) || ytThumb(url)
            }
        });
        state.highlight = id;
        flashButton(btn, $("downloadLabel"), "btnAdded", updateDownloadLabel);
        setTimeout(() => setTab("queue"), 500);
    } catch (e) {
        UI.toast((e && e.message) || OC.t("errUnknown"), "error");
    } finally {
        setTimeout(() => { btn.disabled = false; }, 700);
    }
}

async function showShortcutHint() {
    try {
        const cmds = await browser.commands.getAll();
        const quick = cmds.find(c => c.name === "quick-download");
        if (!quick || !quick.shortcut) return;
        $("shortcutHint").replaceChildren(icon("keyboard", 13), h("kbd", { text: quick.shortcut }), h("span", { text: OC.t("hintQuick") }));
        $("shortcutHint").hidden = false;
    } catch {
        $("shortcutHint").hidden = true;
    }
}

function setupFile() {
    if (!OC.isWebUrl(state.url)) return;
    const type = OC.fileTypeForUrl(state.url);
    if (!type) return;
    state.fileType = type;
    state.fileName = OC.filenameFromUrl(state.url);
    state.fileExt = OC.extOf(state.fileName);
    document.querySelector('.tab[data-tab="file"]').hidden = false;
    const iconName = { image: "image", audio: "audio", video: "video", document: "doc" }[type] || "file";
    $("fileIcon").replaceChildren(icon(iconName, 22));
    $("fileName").textContent = state.fileName;
    $("fileType").textContent = `${OC.t(`type_${type}`)} · ${state.fileExt.toUpperCase()}`;
    const same = new Set([state.fileExt, state.fileExt === "jpeg" ? "jpg" : "", state.fileExt === "markdown" ? "md" : ""]);
    state.targets = OC.TARGETS[type].filter(f => !same.has(f));
    state.target = state.targets[0];
    $("ocrBtn").hidden = type !== "image";
    renderTargets();
}

function renderTargets() {
    $("targetChips").replaceChildren(...state.targets.map(f => h("button", {
        type: "button",
        class: `chip${f === state.target ? " selected" : ""}`,
        onclick: () => {
            state.target = f;
            renderTargets();
        }
    },
    h("span", { class: "chip-label", text: OC.targetLabel(f) }),
    h("span", { class: "chip-sub", text: OC.t(f.startsWith("ocr-") ? "chipOcrSub" : f === "images" ? "chipZipSub" : `type_${OC.TYPE_BY_EXT[f] || state.fileType}`) }))));
    $("convertLabel").textContent = OC.t("btnConvertTo", [OC.targetLabel(state.target)]);
}

async function startConvert(kind) {
    const btn = kind === "ocr" ? $("ocrBtn") : $("convertBtn");
    btn.disabled = true;
    try {
        const id = await send("start-convert", {
            payload: { sourceUrl: state.url, target: kind === "ocr" ? null : state.target, kind, title: state.fileName }
        });
        state.highlight = id;
        setTimeout(() => setTab("queue"), 250);
    } catch (e) {
        UI.toast((e && e.message) || OC.t("errUnknown"), "error");
    } finally {
        setTimeout(() => { btn.disabled = false; }, 700);
    }
}

function jobIcon(job) {
    if (job.kind === "ocr") return "text";
    if (job.kind === "convert") return "convert";
    if (job.isPlaylist) return "list";
    return job.formatLabel === OC.t("fmtAudio") ? "music" : "film";
}

function metaParts(job) {
    const parts = [];
    switch (job.status) {
        case "starting":
            parts.push(job.statusText || OC.t("stStarting"));
            break;
        case "processing":
            parts.push(job.statusText || OC.t("stProcessing"));
            if (job.progress > 0) parts.push(`${Math.floor(job.progress)}%`);
            if (job.speed) parts.push(`${OC.formatBytes(job.speed)}/s`);
            if (job.eta) parts.push(OC.t("lblEta", [OC.formatDuration(job.eta)]));
            break;
        case "saving":
            parts.push(job.statusText || OC.t("stSaving"));
            break;
        case "done":
            parts.push(job.kind === "ocr" && job.statusText ? job.statusText : OC.t("stDone"));
            if (job.formatLabel) parts.push(job.formatLabel);
            if (job.outputSize) parts.push(OC.formatBytes(job.outputSize));
            parts.push(new Date(job.updatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
            break;
        case "error":
            parts.push(job.error || OC.t("errUnknown"));
            break;
        case "cancelled":
            parts.push(OC.t("stCancelled"));
            break;
        default:
            parts.push(job.status);
    }
    return parts;
}

function jobActions(job) {
    const b = (name, titleKey, fn, cls = "") => h("button", {
        type: "button",
        class: `icon-btn ${cls}`,
        title: OC.t(titleKey),
        onclick: fn
    }, icon(name, 15));
    const missing = () => UI.toast(OC.t("errFileMissing"), "error");
    const btns = [];
    if (OC.isActive(job)) {
        btns.push(b("x", "actCancel", () => send("cancel", { id: job.id }), "danger"));
    } else {
        if (job.status === "done" && job.downloadId != null) {
            btns.push(b("play", "actOpen", () => browser.downloads.open(job.downloadId).catch(missing)));
            btns.push(b("folder", "actShow", () => browser.downloads.show(job.downloadId).catch(missing)));
        }
        if (job.kind === "ocr" && job.text) {
            btns.push(b("copy", "actCopy", async () => {
                try {
                    await navigator.clipboard.writeText(job.text);
                    UI.toast(OC.t("toastCopied"));
                } catch {
                    UI.toast(OC.t("errUnknown"), "error");
                }
            }));
        }
        if ((job.status === "error" && job.retryable !== false) || job.status === "cancelled") {
            btns.push(b("retry", "actRetry", () => send("retry", { id: job.id })));
        }
        btns.push(b("trash", "actRemove", () => send("remove", { id: job.id }), "danger"));
    }
    return h("div", { class: "job-actions" }, btns);
}

function jobItem(job) {
    const fallbackIcon = () => icon(jobIcon(job), 18);
    const thumb = h("div", { class: "job-thumb" }, job.thumbnail
        ? h("img", { src: job.thumbnail, alt: "", onerror: e => e.target.replaceWith(fallbackIcon()) })
        : fallbackIcon());
    const parts = metaParts(job);
    const meta = h("div", { class: "job-meta" }, parts.flatMap((p, i) => i === 0
        ? [h("span", { class: "state", text: p })]
        : [h("span", { class: "sep", text: "·" }), h("span", { text: p })]));
    const body = h("div", { class: "job-body" }, h("div", { class: "job-title", title: job.title, text: job.title || "—" }), meta);
    if (OC.isActive(job)) {
        const pct = Math.max(0, Math.min(100, job.progress || 0));
        const indeterminate = job.status !== "processing" || pct <= 0;
        const fill = h("span");
        fill.style.width = `${pct}%`;
        body.append(h("div", { class: `bar${indeterminate ? " indeterminate" : ""}` }, fill));
    }
    if (job.kind === "ocr" && job.text) body.append(h("div", { class: "job-text", text: job.text }));
    return h("div", { class: `job ${job.status}`, dataset: { id: job.id, thumb: job.thumbnail || "" } }, thumb, body, jobActions(job));
}

function renderQueue(jobs) {
    const active = jobs.filter(OC.isActive).length;
    const finished = jobs.length - active;
    $("queueCount").hidden = !active;
    $("queueCount").textContent = String(active);
    $("queueSummary").textContent = jobs.length ? OC.t("queueSummary", [String(active), String(finished)]) : "";
    $("clearFinished").hidden = !finished;
    $("queueEmpty").hidden = jobs.length > 0;

    const list = $("queueList");
    const existing = new Map([...list.children].map(el => [el.dataset.id, el]));
    const seen = new Set();
    jobs.forEach((job, i) => {
        const sig = JSON.stringify([
            job.status, Math.floor(job.progress || 0), job.statusText, job.title, job.error,
            job.speed ? Math.round(job.speed / 51200) : 0, job.eta, job.downloadId, job.outputSize, !!job.text, job.retryable
        ]);
        let el = existing.get(job.id);
        if (!el || el.dataset.sig !== sig) {
            const fresh = jobItem(job);
            fresh.dataset.sig = sig;
            if (el) {
                if (el.dataset.thumb === fresh.dataset.thumb) fresh.querySelector(".job-thumb").replaceWith(el.querySelector(".job-thumb"));
                el.replaceWith(fresh);
            }
            el = fresh;
        }
        if (list.children[i] !== el) list.insertBefore(el, list.children[i] || null);
        seen.add(job.id);
    });
    for (const [id, el] of existing) if (!seen.has(id)) el.remove();

    if (state.highlight) {
        const el = [...list.children].find(c => c.dataset.id === state.highlight);
        if (el) {
            el.classList.add("flash");
            el.scrollIntoView({ block: "nearest" });
            state.highlight = null;
        }
    }
}

function bind() {
    document.querySelectorAll(".tab").forEach(b => b.addEventListener("click", () => setTab(b.dataset.tab)));
    document.querySelectorAll("#ytSwitch button").forEach(b => b.addEventListener("click", () => {
        if (state.ytMode === b.dataset.mode) return;
        state.ytMode = b.dataset.mode;
        syncSwitch();
        loadInfo(false);
    }));
    $("status").addEventListener("click", async () => {
        const ok = await checkServer();
        if (ok && !$("mediaOffline").hidden) loadInfo(true);
    });
    $("openApp").addEventListener("click", async () => {
        await send("open-app", { url: state.url });
        window.close();
    });
    const openSettings = () => {
        browser.runtime.openOptionsPage();
        window.close();
    };
    $("openSettings").addEventListener("click", openSettings);
    $("offlineSettings").addEventListener("click", openSettings);
    $("offlineRetry").addEventListener("click", async () => {
        const ok = await checkServer();
        if (ok) loadInfo(true);
        else UI.toast(OC.t("statusOffline"), "error");
    });
    $("infoRetry").addEventListener("click", () => loadInfo(true));
    $("downloadBtn").addEventListener("click", startDownload);
    $("convertBtn").addEventListener("click", () => startConvert("convert"));
    $("ocrBtn").addEventListener("click", () => startConvert("ocr"));
    $("clearFinished").addEventListener("click", () => send("clear-finished"));
    browser.storage.onChanged.addListener((changes, area) => {
        if (area === "local" && changes.jobs) renderQueue(changes.jobs.newValue || []);
    });
}

async function init() {
    OC.localize();
    UI.renderIcons();
    state.settings = await OC.getSettings();
    bind();
    send("seen").catch(() => {});

    try {
        const [tab] = await browser.tabs.query({ active: true, currentWindow: true });
        if (tab) state.tab = { url: tab.url || "", title: tab.title || "" };
    } catch {
        state.tab = { url: "", title: "" };
    }
    state.url = state.tab.url;

    const { jobs } = await browser.storage.local.get("jobs");
    renderQueue(jobs || []);
    checkServer();
    setupFile();

    if (state.fileType) setTab("file");
    else if (!OC.isWebUrl(state.url) && (jobs || []).length) setTab("queue");
    else setTab("media");
}

document.addEventListener("DOMContentLoaded", init);

const OC = (() => {
    const DEFAULTS = {
        serverUrl: "http://127.0.0.1:5000",
        defaultQuality: "best",
        saveAs: false,
        subfolder: "OmniConv",
        smartRename: false,
        notifications: true,
        ocrLang: (browser.i18n.getUILanguage() || "en").toLowerCase().startsWith("pl") ? "pl" : "en"
    };

    const QUALITY_PRESETS = ["best", "2160", "1440", "1080", "720", "480", "audio"];

    const TYPE_BY_EXT = {
        mp3: "audio", wav: "audio", ogg: "audio", flac: "audio", m4a: "audio", aac: "audio", ac3: "audio",
        alac: "audio", dts: "audio", eac3: "audio", tta: "audio", wv: "audio", aiff: "audio", ape: "audio",
        wma: "audio", opus: "audio",
        mp4: "video", avi: "video", mkv: "video", mov: "video", wmv: "video", flv: "video", webm: "video",
        "3gp": "video", mpeg: "video", mpg: "video", m4v: "video", ts: "video", mts: "video", vob: "video",
        jpg: "image", jpeg: "image", png: "image", gif: "image", bmp: "image", tiff: "image", tif: "image",
        webp: "image", ico: "image", heic: "image", heif: "image",
        pdf: "document", md: "document", markdown: "document"
    };

    const TARGETS = {
        image: ["png", "jpg", "webp", "ico", "ocr-pdf", "ocr-docx", "ocr-txt"],
        document: ["docx", "txt", "md", "html", "pdf", "epub", "xlsx", "images", "ocr-pdf"],
        audio: ["mp3", "wav", "flac", "ogg", "m4a"],
        video: ["mp4", "webm", "mkv", "gif", "mp3", "wav"]
    };

    const LINK_TARGETS = ["mp3", "mp4", "png", "jpg", "webp", "docx", "txt", "md"];

    const MIME_EXT = {
        "image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp", "image/gif": "gif",
        "image/bmp": "bmp", "image/tiff": "tiff", "image/x-icon": "ico", "image/vnd.microsoft.icon": "ico",
        "image/heic": "heic", "image/heif": "heif", "application/pdf": "pdf", "text/markdown": "md",
        "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/wav": "wav", "audio/x-wav": "wav", "audio/wave": "wav",
        "audio/ogg": "ogg", "audio/flac": "flac", "audio/x-flac": "flac", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
        "audio/aac": "aac", "audio/opus": "opus", "video/mp4": "mp4", "video/webm": "webm",
        "video/quicktime": "mov", "video/x-matroska": "mkv", "video/x-msvideo": "avi", "video/mpeg": "mpeg"
    };

    const ACTIVE_STATES = new Set(["starting", "processing", "saving"]);

    class ApiError extends Error {
        constructor(message, extra = {}) {
            super(message);
            Object.assign(this, extra);
        }
    }

    function t(key, subs) {
        return browser.i18n.getMessage(key, subs) || key;
    }

    function localize(root = document) {
        root.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = t(el.dataset.i18n); });
        root.querySelectorAll("[data-i18n-title]").forEach(el => { el.title = t(el.dataset.i18nTitle); });
        root.querySelectorAll("[data-i18n-placeholder]").forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    }

    async function getSettings() {
        const { settings } = await browser.storage.local.get("settings");
        return { ...DEFAULTS, ...(settings || {}) };
    }

    async function saveSettings(patch) {
        const next = { ...(await getSettings()), ...patch };
        await browser.storage.local.set({ settings: next });
        return next;
    }

    function normalizeServer(url) {
        let value = (url || DEFAULTS.serverUrl).trim().replace(/\/+$/, "");
        if (!/^https?:\/\//i.test(value)) value = `http://${value}`;
        return value;
    }

    async function api(path, { method = "GET", json, body, timeout = 30000, server } = {}) {
        const base = normalizeServer(server || (await getSettings()).serverUrl);
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), timeout);
        const init = { method, signal: ctrl.signal };
        if (json !== undefined) {
            init.headers = { "Content-Type": "application/json" };
            init.body = JSON.stringify(json);
        } else if (body) {
            init.body = body;
        }
        let res;
        try {
            res = await fetch(base + path, init);
        } catch (e) {
            const timedOut = e.name === "AbortError";
            throw new ApiError(timedOut ? t("errTimeout") : t("errOffline", [base]), { offline: !timedOut, retryable: true });
        } finally {
            clearTimeout(timer);
        }
        let data = null;
        try {
            data = await res.json();
        } catch {
            data = null;
        }
        if (!res.ok || (data && data.success === false)) {
            const err = data && data.error;
            const message = (typeof err === "string" ? err : err && err.message) || `HTTP ${res.status}`;
            throw new ApiError(message, {
                status: res.status,
                retryable: !(data && data.retry_possible === false),
                category: data && data.category
            });
        }
        return data;
    }

    async function ping(server) {
        try {
            await api("/api/capabilities", { timeout: 3000, server });
            return true;
        } catch {
            return false;
        }
    }

    function presetFormat(preset) {
        if (preset === "audio") return { formatId: "bestaudio/best", formatLabel: t("fmtAudio") };
        if (/^\d+$/.test(String(preset))) return { formatId: `bestvideo[height<=${preset}]`, formatLabel: `${preset}p` };
        return { formatId: "bestvideo+bestaudio/best", formatLabel: t("fmtBest") };
    }

    function serverFormatLabel(f) {
        if (f.format_id === "bestaudio/best") return t("fmtAudio");
        if (f.format_id === "bestvideo+bestaudio/best" || f.format_id === "best") return t("fmtBest");
        const note = /(\d{3,4}p\d*)/.exec(f.note || "");
        if (note) return note[1];
        const res = /(\d+)x(\d+)/.exec(f.resolution || "");
        if (res) return `${Math.min(+res[1], +res[2])}p`;
        return f.resolution || f.note || (f.ext || "?").toUpperCase();
    }

    function labelHeight(label) {
        const m = /^(\d{3,4})p/.exec(label || "");
        return m ? +m[1] : 0;
    }

    function youtubeParts(url) {
        try {
            const u = new URL(url);
            const host = u.hostname.replace(/^(www|m|music)\./, "");
            if (host === "youtube.com" && u.pathname === "/watch") {
                const v = u.searchParams.get("v");
                const list = u.searchParams.get("list");
                return {
                    video: v ? `https://www.youtube.com/watch?v=${v}` : null,
                    playlist: list ? `https://www.youtube.com/playlist?list=${list}` : null
                };
            }
            if (host === "youtu.be") {
                const v = u.pathname.slice(1);
                const list = u.searchParams.get("list");
                return {
                    video: v ? `https://www.youtube.com/watch?v=${v}` : null,
                    playlist: list ? `https://www.youtube.com/playlist?list=${list}` : null
                };
            }
        } catch {
            return null;
        }
        return null;
    }

    function singleVideoUrl(url) {
        const parts = youtubeParts(url);
        return (parts && parts.video) || url;
    }

    function isWebUrl(url) {
        return typeof url === "string" && /^https?:\/\//i.test(url);
    }

    function filenameFromUrl(url) {
        try {
            const u = new URL(url);
            if (!/^https?:$/.test(u.protocol)) return "";
            const seg = u.pathname.split("/").filter(Boolean).pop() || "";
            return decodeURIComponent(seg);
        } catch {
            return "";
        }
    }

    function extOf(name) {
        const m = /\.([a-z0-9]+)$/i.exec(name || "");
        return m ? m[1].toLowerCase() : "";
    }

    function fileTypeForUrl(url) {
        return TYPE_BY_EXT[extOf(filenameFromUrl(url))] || null;
    }

    function sanitizeFilename(name) {
        let clean = String(name || "")
            .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, "")
            .replace(/\s+/g, " ")
            .trim()
            .replace(/[. ]+$/, "");
        if (clean.length > 180) {
            const ext = extOf(clean);
            clean = clean.slice(0, 170 - ext.length).trim() + (ext ? `.${ext}` : "");
        }
        return clean || "download";
    }

    function sanitizeFolder(path) {
        return String(path || "")
            .split(/[\\/]+/)
            .map(seg => seg.replace(/[:*?"<>|\u0000-\u001f]+/g, "").trim().replace(/[. ]+$/, ""))
            .filter(seg => seg && seg !== "." && seg !== "..")
            .join("/");
    }

    function stripJobSuffix(name) {
        return String(name || "").replace(/_[0-9a-f]{8}(?=\.[^.]+$)/i, "");
    }

    function filenameFor(url, disposition, mime) {
        let name = "";
        if (disposition) {
            const star = /filename\*\s*=\s*(?:UTF-8'')?([^;]+)/i.exec(disposition);
            const plain = /filename\s*=\s*"?([^";]+)"?/i.exec(disposition);
            try {
                name = star ? decodeURIComponent(star[1].trim().replace(/^"|"$/g, "")) : plain ? plain[1].trim() : "";
            } catch {
                name = plain ? plain[1].trim() : "";
            }
        }
        if (!name) name = filenameFromUrl(url);
        name = sanitizeFilename(name || "file");
        const ext = extOf(name);
        const mimeExt = MIME_EXT[String(mime || "").split(";")[0].trim().toLowerCase()];
        if ((!ext || !TYPE_BY_EXT[ext]) && mimeExt) {
            name = `${name.replace(/\.[^.]*$/, "") || "file"}.${mimeExt}`;
        }
        return name;
    }

    function targetLabel(fmt) {
        const f = String(fmt || "").toLowerCase();
        if (f.startsWith("ocr-")) return `${f.slice(4).toUpperCase()} (OCR)`;
        if (f === "pdf_ocr") return "PDF (OCR)";
        if (f === "images") return t("fmtImages");
        return f.toUpperCase();
    }

    function formatBytes(bytes) {
        if (!bytes || bytes <= 0) return "";
        const units = ["B", "KB", "MB", "GB", "TB"];
        let i = 0;
        let n = bytes;
        while (n >= 1024 && i < units.length - 1) {
            n /= 1024;
            i++;
        }
        return `${n >= 100 || i === 0 ? Math.round(n) : n.toFixed(1)} ${units[i]}`;
    }

    function formatDuration(sec) {
        if (sec == null || !isFinite(sec) || sec < 0) return "";
        const s = Math.round(sec);
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const r = String(s % 60).padStart(2, "0");
        return h ? `${h}:${String(m).padStart(2, "0")}:${r}` : `${m}:${r}`;
    }

    function uid() {
        return crypto.randomUUID();
    }

    function isActive(job) {
        return ACTIVE_STATES.has(job.status);
    }

    function cacheStore() {
        return browser.storage.session || browser.storage.local;
    }

    async function cacheGet(key, ttlMs) {
        const k = `cache:${key}`;
        const entry = (await cacheStore().get(k))[k];
        return entry && Date.now() - entry.at < ttlMs ? entry.value : null;
    }

    async function cacheSet(key, value) {
        await cacheStore().set({ [`cache:${key}`]: { at: Date.now(), value } });
    }

    return {
        DEFAULTS, QUALITY_PRESETS, TYPE_BY_EXT, TARGETS, LINK_TARGETS, ACTIVE_STATES, ApiError,
        t, localize, getSettings, saveSettings, normalizeServer, api, ping,
        presetFormat, serverFormatLabel, labelHeight, youtubeParts, singleVideoUrl, isWebUrl,
        filenameFromUrl, extOf, fileTypeForUrl, sanitizeFilename, sanitizeFolder, stripJobSuffix, filenameFor,
        targetLabel, formatBytes, formatDuration, uid, isActive, cacheGet, cacheSet
    };
})();

const $ = id => document.getElementById(id);

const QUALITY_KEYS = {
    best: "qualityBest",
    "2160": "quality2160",
    "1440": "quality1440",
    "1080": "quality1080",
    "720": "quality720",
    "480": "quality480",
    audio: "qualityAudio"
};

async function save(patch) {
    await OC.saveSettings(patch);
    UI.toast(OC.t("toastSaved"));
}

async function testServer() {
    const result = $("testResult");
    const url = OC.normalizeServer($("serverUrl").value);
    result.className = "test-result";
    result.textContent = OC.t("statusChecking");
    const ok = await OC.ping(url);
    result.className = `test-result ${ok ? "ok" : "bad"}`;
    result.textContent = ok ? OC.t("optTestOk", [url]) : OC.t("optTestFail", [url]);
}

async function renderShortcuts() {
    const box = $("shortcuts");
    const cmds = await browser.commands.getAll();
    box.replaceChildren(...cmds.map(c => UI.h("div", { class: "shortcut" },
        UI.h("span", { text: c.description || (c.name === "_execute_action" ? OC.t("cmdOpen") : c.name) }),
        UI.h("kbd", { text: c.shortcut || OC.t("optNoShortcut") }))));
    if (browser.commands.openShortcutSettings) {
        $("editShortcuts").hidden = false;
        $("editShortcuts").addEventListener("click", () => browser.commands.openShortcutSettings());
    }
}

async function init() {
    OC.localize();
    UI.renderIcons();
    document.title = OC.t("optTitle");

    const quality = $("defaultQuality");
    for (const key of OC.QUALITY_PRESETS) {
        quality.append(UI.h("option", { value: key, text: OC.t(QUALITY_KEYS[key]) }));
    }

    const s = await OC.getSettings();
    $("serverUrl").value = s.serverUrl;
    quality.value = s.defaultQuality;
    $("subfolder").value = s.subfolder;
    $("saveAs").checked = s.saveAs;
    $("smartRename").checked = s.smartRename;
    $("notifications").checked = s.notifications;
    $("ocrLang").value = s.ocrLang;

    $("serverUrl").addEventListener("change", async e => {
        const value = OC.normalizeServer(e.target.value);
        e.target.value = value;
        await save({ serverUrl: value });
        testServer();
    });
    $("testServer").addEventListener("click", testServer);
    quality.addEventListener("change", e => save({ defaultQuality: e.target.value }));
    $("subfolder").addEventListener("change", e => {
        const value = OC.sanitizeFolder(e.target.value);
        e.target.value = value;
        save({ subfolder: value });
    });
    for (const id of ["saveAs", "smartRename", "notifications"]) {
        $(id).addEventListener("change", e => save({ [id]: e.target.checked }));
    }
    $("ocrLang").addEventListener("change", e => save({ ocrLang: e.target.value }));
    $("clearHistory").addEventListener("click", async () => {
        await browser.runtime.sendMessage({ type: "clear-finished" });
        UI.toast(OC.t("toastCleared"));
    });

    renderShortcuts();
    testServer();
}

document.addEventListener("DOMContentLoaded", init);

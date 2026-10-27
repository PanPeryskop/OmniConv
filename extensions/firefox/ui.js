const UI = (() => {
    const NS = "http://www.w3.org/2000/svg";

    const ICONS = {
        download: [["path", {d: "M12 15V3"}], ["path", {d: "M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"}], ["path", {d: "m7 10 5 5 5-5"}]],
        music: [["path", {d: "M21 16V3a1 1 0 0 0-1.28-.96l-10 2.917a1 1 0 0 0-.72.96V19"}], ["circle", {cx: 18, cy: 16, r: 3}], ["circle", {cx: 6, cy: 19, r: 3}]],
        film: [["path", {d: "m12.296 3.464 3.02 3.956"}], ["path", {d: "M20.2 6 3 11l-.9-2.4c-.3-1.1.3-2.2 1.3-2.5l13.5-4c1.1-.3 2.2.3 2.5 1.3z"}], ["path", {d: "M3 11h18v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"}], ["path", {d: "m6.18 5.276 3.1 3.899"}]],
        sliders: [["path", {d: "M10 5H3"}], ["path", {d: "M12 19H3"}], ["path", {d: "M14 3v4"}], ["path", {d: "M16 17v4"}], ["path", {d: "M21 12h-9"}], ["path", {d: "M21 19h-5"}], ["path", {d: "M21 5h-7"}], ["path", {d: "M8 10v4"}], ["path", {d: "M8 12H3"}]],
        external: [["path", {d: "M15 3h6v6"}], ["path", {d: "M10 14 21 3"}], ["path", {d: "M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"}]],
        x: [["path", {d: "M18 6 6 18"}], ["path", {d: "m6 6 12 12"}]],
        retry: [["path", {d: "M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"}], ["path", {d: "M21 3v5h-5"}]],
        folder: [["path", {d: "m6 14 1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"}]],
        play: [["path", {d: "M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"}]],
        trash: [["path", {d: "M10 11v6"}], ["path", {d: "M14 11v6"}], ["path", {d: "M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"}], ["path", {d: "M3 6h18"}], ["path", {d: "M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"}]],
        copy: [["rect", {width: 14, height: 14, x: 8, y: 8, rx: 2, ry: 2}], ["path", {d: "M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"}]],
        file: [["path", {d: "M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"}], ["path", {d: "M14 2v5a1 1 0 0 0 1 1h5"}]],
        doc: [["path", {d: "M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"}], ["path", {d: "M14 2v5a1 1 0 0 0 1 1h5"}], ["path", {d: "M10 9H8"}], ["path", {d: "M16 13H8"}], ["path", {d: "M16 17H8"}]],
        image: [["rect", {width: 18, height: 18, x: 3, y: 3, rx: 2, ry: 2}], ["circle", {cx: 9, cy: 9, r: 2}], ["path", {d: "m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"}]],
        text: [["path", {d: "M3 7V5a2 2 0 0 1 2-2h2"}], ["path", {d: "M17 3h2a2 2 0 0 1 2 2v2"}], ["path", {d: "M21 17v2a2 2 0 0 1-2 2h-2"}], ["path", {d: "M7 21H5a2 2 0 0 1-2-2v-2"}], ["path", {d: "M7 8h8"}], ["path", {d: "M7 12h10"}], ["path", {d: "M7 16h6"}]],
        list: [["path", {d: "M21 5H3"}], ["path", {d: "M10 12H3"}], ["path", {d: "M10 19H3"}], ["path", {d: "M15 12.003a1 1 0 0 1 1.517-.859l4.997 2.997a1 1 0 0 1 0 1.718l-4.997 2.997a1 1 0 0 1-1.517-.86z"}]],
        queue: [["path", {d: "M13 5h8"}], ["path", {d: "M13 12h8"}], ["path", {d: "M13 19h8"}], ["path", {d: "m3 17 2 2 4-4"}], ["path", {d: "m3 7 2 2 4-4"}]],
        zap: [["path", {d: "M15.914 4a1.5 1.5 0 00-2.474-1.561l-9 9A1.5 1.5 0 005.5 14h4.002a.5.5 0 01.471.666L8.086 20a1.5 1.5 0 002.475 1.56l9-9A1.5 1.5 0 0018.5 10h-3.997a.5.5 0 01-.472-.667z"}]],
        alert: [["circle", {cx: 12, cy: 12, r: 10}], ["line", {x1: 12,x2: 12,y1: 8,y2: 12}], ["line", {x1: 12,x2: 12.01,y1: 16,y2: 16}]],
        check: [["path", {d: "M20 6 9 17l-5-5"}]],
        inbox: [["polyline", {points: "22 12 16 12 14 15 10 15 8 12 2 12"}], ["path", {d: "M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"}]],
        power: [["path", {d: "M12 2v10"}], ["path", {d: "M18.4 6.6a9 9 0 1 1-12.77.04"}]],
        globe: [["circle", {cx: 12, cy: 12, r: 10}], ["path", {d: "M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"}], ["path", {d: "M2 12h20"}]],
        keyboard: [["path", {d: "M10 8h.01"}], ["path", {d: "M12 12h.01"}], ["path", {d: "M14 8h.01"}], ["path", {d: "M16 12h.01"}], ["path", {d: "M18 8h.01"}], ["path", {d: "M6 8h.01"}], ["path", {d: "M7 16h10"}], ["path", {d: "M8 12h.01"}], ["rect", {width: 20, height: 16, x: 2, y: 4, rx: 2}]],
        offline: [["path", {d: "M12 20h.01"}], ["path", {d: "M8.5 16.429a5 5 0 0 1 7 0"}], ["path", {d: "M5 12.859a10 10 0 0 1 5.17-2.69"}], ["path", {d: "M19 12.859a10 10 0 0 0-2.007-1.523"}], ["path", {d: "M2 8.82a15 15 0 0 1 4.177-2.643"}], ["path", {d: "M22 8.82a15 15 0 0 0-11.288-3.764"}], ["path", {d: "m2 2 20 20"}]],
        sparkles: [["path", {d: "M11.017 2.814a1 1 0 0 1 1.966 0l1.051 5.558a2 2 0 0 0 1.594 1.594l5.558 1.051a1 1 0 0 1 0 1.966l-5.558 1.051a2 2 0 0 0-1.594 1.594l-1.051 5.558a1 1 0 0 1-1.966 0l-1.051-5.558a2 2 0 0 0-1.594-1.594l-5.558-1.051a1 1 0 0 1 0-1.966l5.558-1.051a2 2 0 0 0 1.594-1.594z"}], ["path", {d: "M20 2v4"}], ["path", {d: "M22 4h-4"}], ["circle", {cx: 4, cy: 20, r: 2}]],
        audio: [["path", {d: "M2 10v3"}], ["path", {d: "M6 6v11"}], ["path", {d: "M10 3v18"}], ["path", {d: "M14 8v7"}], ["path", {d: "M18 5v13"}], ["path", {d: "M22 10v3"}]],
        video: [["path", {d: "m16 13 5.223 3.482a.5.5 0 0 0 .777-.416V7.87a.5.5 0 0 0-.752-.432L16 10.5"}], ["rect", {x: 2, y: 6, width: 14, height: 12, rx: 2}]],
        loader: [["path", {d: "M21 12a9 9 0 1 1-6.219-8.56"}]],
        convert: [["path", {d: "m2 9 3-3 3 3"}], ["path", {d: "M13 18H7a2 2 0 0 1-2-2V6"}], ["path", {d: "m22 15-3 3-3-3"}], ["path", {d: "M11 6h6a2 2 0 0 1 2 2v10"}]],
        server: [["rect", {width: 20, height: 8, x: 2, y: 2, rx: 2, ry: 2}], ["rect", {width: 20, height: 8, x: 2, y: 14, rx: 2, ry: 2}], ["line", {x1: 6,x2: 6.01,y1: 6,y2: 6}], ["line", {x1: 6,x2: 6.01,y1: 18,y2: 18}]]
    };

    function icon(name, size = 16) {
        const svg = document.createElementNS(NS, "svg");
        const attrs = {
            viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
            "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true"
        };
        for (const [k, v] of Object.entries(attrs)) svg.setAttribute(k, v);
        for (const [tag, props] of ICONS[name] || []) {
            const node = document.createElementNS(NS, tag);
            for (const [k, v] of Object.entries(props)) node.setAttribute(k, v);
            svg.appendChild(node);
        }
        return svg;
    }

    function renderIcons(root = document) {
        root.querySelectorAll("[data-icon]").forEach(el => {
            el.replaceChildren(icon(el.dataset.icon, +el.dataset.size || 16));
        });
    }

    function h(tag, props = {}, ...children) {
        const el = document.createElement(tag);
        for (const [k, v] of Object.entries(props)) {
            if (v == null || v === false) continue;
            if (k === "class") el.className = v;
            else if (k === "text") el.textContent = v;
            else if (k === "dataset") Object.assign(el.dataset, v);
            else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
            else el.setAttribute(k, v === true ? "" : v);
        }
        for (const child of children.flat()) {
            if (child != null && child !== false) el.append(child);
        }
        return el;
    }

    let toastTimer = null;

    function toast(message, kind = "") {
        let el = document.getElementById("toast");
        if (!el) {
            el = h("div", { id: "toast", class: "toast", role: "status" });
            document.body.appendChild(el);
        }
        el.textContent = message;
        el.className = `toast show ${kind}`;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { el.className = `toast ${kind}`; }, 2200);
    }

    return { icon, renderIcons, h, toast };
})();

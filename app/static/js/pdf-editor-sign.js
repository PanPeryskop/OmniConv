const PdfSign = (() => {
    const KEY = 'pe-signatures';
    const LIMIT = 6;
    const FONTS = [
        "'Segoe Script', 'Lucida Handwriting', 'Brush Script MT', 'URW Chancery L', cursive",
        "'Ink Free', 'Bradley Hand', 'Comic Sans MS', cursive",
        "'Brush Script MT', 'Snell Roundhand', 'Segoe Script', cursive"
    ];

    function list() {
        try {
            const items = JSON.parse(localStorage.getItem(KEY));
            return Array.isArray(items) ? items : [];
        } catch (err) {
            return [];
        }
    }

    function store(items) {
        try {
            localStorage.setItem(KEY, JSON.stringify(items.slice(0, LIMIT)));
        } catch (err) {
            return;
        }
    }

    function add(url) {
        const items = list().filter(item => item.url !== url);
        items.unshift({ id: Date.now().toString(36), url });
        store(items);
        return items[0];
    }

    function remove(id) {
        store(list().filter(item => item.id !== id));
    }

    function trim(canvas, margin = 6) {
        const ctx = canvas.getContext('2d', { willReadFrequently: true });
        const { data, width, height } = ctx.getImageData(0, 0, canvas.width, canvas.height);
        let x0 = width, y0 = height, x1 = -1, y1 = -1;
        for (let y = 0; y < height; y++) {
            for (let x = 0; x < width; x++) {
                if (data[(y * width + x) * 4 + 3] > 16) {
                    if (x < x0) x0 = x;
                    if (x > x1) x1 = x;
                    if (y < y0) y0 = y;
                    if (y > y1) y1 = y;
                }
            }
        }
        if (x1 < 0) return null;
        x0 = Math.max(0, x0 - margin);
        y0 = Math.max(0, y0 - margin);
        x1 = Math.min(width - 1, x1 + margin);
        y1 = Math.min(height - 1, y1 + margin);
        const out = document.createElement('canvas');
        out.width = x1 - x0 + 1;
        out.height = y1 - y0 + 1;
        out.getContext('2d').drawImage(canvas, x0, y0, out.width, out.height, 0, 0, out.width, out.height);
        return out.toDataURL('image/png');
    }

    function pad(canvas, color) {
        const ctx = canvas.getContext('2d');
        let drawing = false;
        let last = null;
        let empty = true;
        const ratio = window.devicePixelRatio || 1;
        const resize = () => {
            const rect = canvas.getBoundingClientRect();
            canvas.width = Math.round(rect.width * ratio);
            canvas.height = Math.round(rect.height * ratio);
            empty = true;
        };
        const point = e => {
            const rect = canvas.getBoundingClientRect();
            return [(e.clientX - rect.left) * ratio, (e.clientY - rect.top) * ratio, e.pressure || 0.5];
        };
        canvas.addEventListener('pointerdown', e => {
            drawing = true;
            last = point(e);
            canvas.setPointerCapture(e.pointerId);
            e.preventDefault();
        });
        canvas.addEventListener('pointermove', e => {
            if (!drawing) return;
            const next = point(e);
            ctx.strokeStyle = color();
            ctx.lineCap = 'round';
            ctx.lineJoin = 'round';
            ctx.lineWidth = ratio * (1.6 + next[2] * 2.2);
            ctx.beginPath();
            ctx.moveTo(last[0], last[1]);
            ctx.lineTo(next[0], next[1]);
            ctx.stroke();
            last = next;
            empty = false;
        });
        const stop = () => { drawing = false; };
        canvas.addEventListener('pointerup', stop);
        canvas.addEventListener('pointercancel', stop);
        resize();
        return {
            clear: () => {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                empty = true;
            },
            isEmpty: () => empty,
            result: () => (empty ? null : trim(canvas))
        };
    }

    function typed(text, font, color) {
        const canvas = document.createElement('canvas');
        const ctx = canvas.getContext('2d');
        const size = 96;
        ctx.font = `${size}px ${font}`;
        canvas.width = Math.ceil(ctx.measureText(text).width + size);
        canvas.height = Math.ceil(size * 1.8);
        ctx.font = `${size}px ${font}`;
        ctx.fillStyle = color;
        ctx.textBaseline = 'middle';
        ctx.fillText(text, size / 2, canvas.height / 2);
        return trim(canvas);
    }

    function cleanImage(file) {
        return new Promise((resolve, reject) => {
            const url = URL.createObjectURL(file);
            const img = new Image();
            img.onload = () => {
                URL.revokeObjectURL(url);
                const scale = Math.min(1, 1600 / Math.max(img.naturalWidth, img.naturalHeight));
                const canvas = document.createElement('canvas');
                canvas.width = Math.max(1, Math.round(img.naturalWidth * scale));
                canvas.height = Math.max(1, Math.round(img.naturalHeight * scale));
                const ctx = canvas.getContext('2d', { willReadFrequently: true });
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height);
                const d = pixels.data;
                for (let i = 0; i < d.length; i += 4) {
                    const light = Math.min(d[i], d[i + 1], d[i + 2]);
                    if (light > 235) d[i + 3] = 0;
                    else if (light > 200) d[i + 3] = Math.round(d[i + 3] * (235 - light) / 35);
                }
                ctx.putImageData(pixels, 0, 0);
                resolve(trim(canvas));
            };
            img.onerror = () => {
                URL.revokeObjectURL(url);
                reject(new Error('image'));
            };
            img.src = url;
        });
    }

    async function toFile(dataUrl, name = 'signature.png') {
        const blob = await (await fetch(dataUrl)).blob();
        return new File([blob], name, { type: 'image/png' });
    }

    function size(dataUrl) {
        return new Promise(resolve => {
            const img = new Image();
            img.onload = () => resolve([img.naturalWidth || 1, img.naturalHeight || 1]);
            img.onerror = () => resolve([3, 1]);
            img.src = dataUrl;
        });
    }

    return { FONTS, list, add, remove, pad, typed, cleanImage, toFile, size };
})();

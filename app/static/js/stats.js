const OmniStats = (() => {
    const KEY = 'omniconv_stats';
    const MAX_RECENT = 50;

    function empty() {
        return { version: 1, total: 0, savedBytes: 0, formats: {}, recent: [] };
    }

    function get() {
        try {
            const data = JSON.parse(localStorage.getItem(KEY));
            if (data && data.version === 1) return data;
        } catch (e) {}
        return empty();
    }

    function save(data) {
        try { localStorage.setItem(KEY, JSON.stringify(data)); } catch (e) {}
    }

    function record({ jobId = null, kind = 'conversion', from = '', to = '', inputSize = 0, outputSize = 0 }) {
        const data = get();
        if (jobId && data.recent.some(item => item.jobId === jobId)) return;
        from = String(from || '').toLowerCase();
        to = String(to || '').toLowerCase();
        data.total += 1;
        if (inputSize && outputSize && outputSize < inputSize) data.savedBytes += inputSize - outputSize;
        const formatKey = kind === 'pdf' ? `pdf:${to}` : `${from}->${to}`;
        data.formats[formatKey] = (data.formats[formatKey] || 0) + 1;
        data.recent.unshift({ jobId, kind, from, to, ts: Date.now() });
        data.recent = data.recent.slice(0, MAX_RECENT);
        save(data);
    }

    async function recordJob(jobId, kind, from, to) {
        let inputSize = 0;
        let outputSize = 0;
        try {
            const res = await fetch(`/api/status/${jobId}`);
            const body = await res.json();
            inputSize = body.data?.input_size || 0;
            outputSize = body.data?.output_size || 0;
        } catch (e) {}
        record({ jobId, kind, from, to, inputSize, outputSize });
    }

    function extOf(filename) {
        const match = /\.([^.]+)$/.exec(filename || '');
        return match ? match[1].toLowerCase() : '';
    }

    function clear() {
        try { localStorage.removeItem(KEY); } catch (e) {}
    }

    return { get, record, recordJob, extOf, clear };
})();

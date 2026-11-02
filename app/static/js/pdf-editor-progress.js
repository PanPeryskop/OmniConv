const PdfProgress = (() => {
    const handlers = {};
    const tasks = new Map();
    let timer = 0;
    let fileId = null;

    function emit(task) {
        [...(handlers[task.kind] || []), ...(handlers['*'] || [])].forEach(fn => {
            try {
                fn(task);
            } catch (err) {
                console.error(err);
            }
        });
    }

    function remember(task) {
        const previous = tasks.get(task.id);
        tasks.set(task.id, task);
        if (!previous || previous.updated_at !== task.updated_at || previous.status !== task.status) emit(task);
    }

    async function poll() {
        timer = 0;
        if (!fileId) return;
        const res = await fetch(`/api/pdf/edit/tasks?file_id=${encodeURIComponent(fileId)}`).then(r => r.json()).catch(() => null);
        (res?.data?.tasks || []).forEach(remember);
        const active = [...tasks.values()].some(task => !['done', 'failed', 'cancelled'].includes(task.status));
        if (fileId) timer = setTimeout(poll, active ? 1000 : 3000);
    }

    function start(id) {
        fileId = id;
        clearTimeout(timer);
        poll();
    }

    function stop() {
        fileId = null;
        clearTimeout(timer);
        timer = 0;
        tasks.clear();
    }

    function onTask(kind, fn) {
        (handlers[kind] ||= []).push(fn);
    }

    function track(taskId) {
        if (!timer && fileId) poll();
        return taskId;
    }

    function get(taskId) {
        return tasks.get(taskId) || null;
    }

    function local(kind, options = {}) {
        const now = Date.now() / 1000;
        const task = { id: `local_${Math.random().toString(36).slice(2)}`, kind, status: 'running', progress: null, detail: {}, created_at: now, updated_at: now, ...options };
        const touch = fields => {
            Object.assign(task, fields, { updated_at: Date.now() / 1000 });
            remember({ ...task });
        };
        touch({});
        return {
            task,
            update: fields => touch(fields),
            done: () => touch({ status: 'done', progress: 1 }),
            fail: code => touch({ status: 'failed', error: { code } }),
            cancelled: () => task.status === 'cancelled'
        };
    }

    PdfEditor.bridge.on('open', session => start(session.fileId));
    PdfEditor.bridge.on('close', stop);

    return { onTask, track, get, local };
})();

const PdfProgress = (() => {
    const handlers = {};

    function onTask(kind, fn) {
        (handlers[kind] ||= []).push(fn);
    }

    function track(taskId) {
        return taskId;
    }

    function get() {
        return null;
    }

    function local(kind, options = {}) {
        const task = { id: `local_${Date.now().toString(36)}`, kind, status: 'running', progress: null, detail: {}, ...options };
        return {
            task,
            update(fields) {
                Object.assign(task, fields);
            },
            done() {
                task.status = 'done';
            },
            fail(code) {
                task.status = 'failed';
                task.error = { code };
            },
            cancelled: () => task.status === 'cancelled'
        };
    }

    return { onTask, track, get, local };
})();

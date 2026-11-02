const PdfDrafts = (() => {
    const PREFIX = 'pe-draft:';
    const MAX_AGE = 14 * 24 * 3600 * 1000;
    const DB_NAME = 'omniconv-pdf-editor';
    const STORE = 'images';
    let database = null;

    function storage() {
        try {
            return window.localStorage;
        } catch (err) {
            return null;
        }
    }

    function read(digest) {
        try {
            const raw = storage()?.getItem(PREFIX + digest);
            const draft = raw ? JSON.parse(raw) : null;
            return draft && Array.isArray(draft.ops) && draft.ops.length ? draft : null;
        } catch (err) {
            return null;
        }
    }

    function write(digest, ops) {
        try {
            if (!ops.length) storage()?.removeItem(PREFIX + digest);
            else storage()?.setItem(PREFIX + digest, JSON.stringify({ ops, savedAt: Date.now() }));
        } catch (err) {
            return;
        }
    }

    function remove(digest) {
        try {
            storage()?.removeItem(PREFIX + digest);
        } catch (err) {
            return;
        }
    }

    function drafts() {
        const store = storage();
        if (!store) return [];
        const found = [];
        for (let i = 0; i < store.length; i++) {
            const key = store.key(i);
            if (!key?.startsWith(PREFIX)) continue;
            const draft = read(key.slice(PREFIX.length));
            found.push([key.slice(PREFIX.length), draft]);
        }
        return found;
    }

    function openDb() {
        if (!window.indexedDB) return Promise.reject(new Error('indexedDB unavailable'));
        database ||= new Promise((resolve, reject) => {
            const req = indexedDB.open(DB_NAME, 1);
            req.onupgradeneeded = () => req.result.createObjectStore(STORE);
            req.onsuccess = () => resolve(req.result);
            req.onerror = () => reject(req.error);
        });
        return database;
    }

    function run(mode, action) {
        return openDb().then(db => new Promise((resolve, reject) => {
            const tx = db.transaction(STORE, mode);
            const req = action(tx.objectStore(STORE));
            tx.oncomplete = () => resolve(req?.result);
            tx.onerror = () => reject(tx.error);
        }));
    }

    const putImage = (id, blob) => run('readwrite', store => store.put(blob, id)).catch(() => null);
    const getImage = id => run('readonly', store => store.get(id)).catch(() => null);

    function imageIds(ops) {
        return ops.filter(op => op.type === 'image' && op.file_id).map(op => op.file_id);
    }

    async function prune() {
        const keep = new Set();
        drafts().forEach(([digest, draft]) => {
            if (!draft || Date.now() - draft.savedAt > MAX_AGE) remove(digest);
            else imageIds(draft.ops).forEach(id => keep.add(id));
        });
        const keys = await run('readonly', store => store.getAllKeys()).catch(() => []);
        const stale = (keys || []).filter(id => !keep.has(id));
        if (stale.length) await run('readwrite', store => stale.forEach(id => store.delete(id))).catch(() => null);
    }

    return { read, write, remove, putImage, getImage, imageIds, prune };
})();

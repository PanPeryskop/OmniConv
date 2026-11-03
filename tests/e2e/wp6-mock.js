const fs = require('fs');
const os = require('os');
const path = require('path');

const OK_STATUS = { status: 'ok', provider: 'lmstudio', model: 'qwen2.5-7b-instruct' };
const SHOTS = process.env.E2E_SHOTS || path.join(os.tmpdir(), 'wp6-shots');

function sse(events) {
    return events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join(': ping\n\n');
}

async function mockAgent(page, { status = OK_STATUS, wrap = true, turns = [], stream = null } = {}) {
    const log = { messages: [], feedback: [], stops: 0, sessions: 0, status: 0 };
    const json = data => ({ status: 200, contentType: 'application/json', body: JSON.stringify(wrap ? { success: true, data, error: null } : data) });
    await page.route('**/api/pdf/edit/agent/**', async route => {
        const request = route.request();
        const url = new URL(request.url());
        const parts = url.pathname.split('/');
        const last = parts[parts.length - 1];
        if (last === 'status') {
            log.status++;
            return route.fulfill(json(typeof status === 'function' ? status(log) : status));
        }
        if (last === 'sessions') {
            log.sessions++;
            return route.fulfill(json({ session_id: `ses_${log.sessions}` }));
        }
        if (last === 'messages') {
            const body = request.postDataJSON();
            log.messages.push({ session: parts[parts.length - 2], body });
            if (stream) return route.continue({ url: stream });
            const turn = typeof turns === 'function' ? await turns(body, log) : turns[log.messages.length - 1];
            if (turn && !Array.isArray(turn)) return route.fulfill({ status: turn.status, contentType: 'application/json', body: JSON.stringify({ success: false, data: null, error: turn.error }) });
            const events = turn || [['task', { task_id: 'tsk_empty' }], ['message', { role: 'assistant', text: 'Nothing to do.' }], ['done', { usage: { steps: 1, tool_calls: 0 }, stopped: false }]];
            return route.fulfill({ status: 200, headers: { 'content-type': 'text/event-stream; charset=utf-8', 'cache-control': 'no-cache' }, body: sse(events) });
        }
        if (last === 'stop') {
            log.stops++;
            return route.fulfill(json({ stopped: true }));
        }
        if (last === 'feedback') {
            log.feedback.push(request.postDataJSON());
            return route.fulfill(json({}));
        }
        return route.fulfill({ status: 404, body: '{}' });
    });
    return log;
}

function blockText(block) {
    return block.lines.map(line => line.spans.map(span => span.t).join('')).join(' ');
}

function textOp(page, block, text) {
    return {
        type: 'text', page,
        remove: block.lines.flatMap(line => line.rects),
        rect: block.bbox, baseline: block.baseline, lh: block.lh,
        align: block.align, family: 'original', grow: block.lines.every(line => line.brk),
        runs: [{ ...block.lines[0].spans[0], t: text }]
    };
}

function textProposal(id, page, block, after, { title, reason, base = { count: 0, last_g: null }, depends_on = [] } = {}) {
    const before = blockText(block);
    return {
        id, kind: 'text', page, title: title || `Fix “${before}”`, reason: reason || `“${before}” → “${after}”`,
        before, after, rects: [block.bbox], ops: [textOp(page, block, after)], base, depends_on
    };
}

function turn(text, proposals, { tools = true } = {}) {
    const events = [['task', { task_id: 'tsk_agent_1' }]];
    if (tools) {
        events.push(['tool', { call_id: 'c1', name: 'read_page', args: { page: 0 }, status: 'start', summary: '' }]);
        events.push(['tool', { call_id: 'c1', name: 'read_page', args: { page: 0 }, status: 'done', summary: '12 blocks' }]);
        events.push(['tool', { call_id: 'c2', name: 'proofread', args: { pages: [0] }, status: 'start', summary: '' }]);
    }
    proposals.forEach(p => events.push(['proposal', p]));
    if (tools) events.push(['tool', { call_id: 'c2', name: 'proofread', args: { pages: [0] }, status: 'done', summary: `${proposals.length} fixes` }]);
    const words = text.split(/(?<= )/);
    words.forEach(word => events.push(['delta', { text: word }]));
    events.push(['message', { role: 'assistant', text }]);
    events.push(['done', { usage: { steps: 3, tool_calls: 2 }, stopped: false }]);
    return events;
}

async function layouts(page, ids) {
    return page.evaluate(async list => Object.fromEntries(await Promise.all(list.map(async id => [id, await PdfEditor.bridge.layout(id)]))), ids);
}

async function openAgent(page) {
    await page.click('#peAgentBtn');
    await page.waitForSelector('#peSide:not(.hidden) .pa');
    await page.waitForFunction(() => !document.querySelector('.pa-model .pa-skeleton'));
}

async function sendText(page, text) {
    await page.fill('.pa-input', text);
    await page.press('.pa-input', 'Enter');
}

async function idle(page) {
    await page.waitForFunction(() => !document.querySelector('.pa.busy'));
}

const changes = page => page.textContent('#peStatus');

function shotPath(name) {
    fs.mkdirSync(SHOTS, { recursive: true });
    return path.join(SHOTS, `${name}.png`);
}

async function layoutIssues(page, selector = '#peSide') {
    return page.evaluate(sel => {
        const issues = [];
        const vw = document.documentElement.clientWidth;
        const vh = window.innerHeight;
        if (document.documentElement.scrollWidth > vw + 1) issues.push(`page scrollWidth ${document.documentElement.scrollWidth} > ${vw}`);
        const root = document.querySelector(sel);
        if (!root) return ['panel missing'];
        const box = root.getBoundingClientRect();
        if (box.left < -1 || box.right > vw + 1 || box.top < -1 || box.bottom > vh + 1) issues.push(`panel offscreen ${JSON.stringify(box)}`);
        root.querySelectorAll('*').forEach(node => {
            const r = node.getBoundingClientRect();
            if (!r.width || !r.height) return;
            const style = getComputedStyle(node);
            if (style.visibility === 'hidden' || style.position === 'absolute' && style.clipPath !== 'none') return;
            if (r.right > vw + 1 || r.left < -1) issues.push(`${node.tagName}.${node.className} x ${Math.round(r.left)}..${Math.round(r.right)}`);
            if (node.scrollWidth > node.clientWidth + 1 && !['auto', 'scroll', 'hidden'].includes(style.overflowX) && node.clientWidth) issues.push(`${node.tagName}.${node.className} overflows ${node.scrollWidth} > ${node.clientWidth}`);
        });
        const log = root.querySelector('.pa-log');
        if (log && log.scrollWidth > log.clientWidth + 1) issues.push(`log scrolls horizontally ${log.scrollWidth} > ${log.clientWidth}`);
        return issues;
    }, selector);
}

module.exports = { OK_STATUS, SHOTS, sse, mockAgent, blockText, textOp, textProposal, turn, layouts, openAgent, sendText, idle, changes, shotPath, layoutIssues };

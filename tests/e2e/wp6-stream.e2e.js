const http = require('http');
const { chromium } = require('playwright');
const { startApp, openEditor, check } = require('./helpers');
const { mockAgent, openAgent, sendText, idle } = require('./wp6-mock');

function streamServer(port) {
    const state = { open: 0, closed: 0, writes: 0 };
    const server = http.createServer((req, res) => {
        req.resume();
        state.open++;
        res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache', Connection: 'keep-alive' });
        const send = (type, data) => {
            state.writes++;
            res.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
        };
        send('task', { task_id: 'tsk_stream' });
        send('tool', { call_id: 'c1', name: 'read_page', args: { page: 0 }, status: 'start', summary: '' });
        const words = ['Reading ', 'the ', 'page ', 'and ', 'looking ', 'for ', 'typos ', 'one ', 'word ', 'at ', 'a ', 'time '];
        let i = 0;
        const timer = setInterval(() => {
            if (i === 2) res.write(': ping\n\n');
            send('tool', { call_id: 'c1', name: 'read_page', args: { page: 0 }, status: 'progress', done: Math.min(i + 1, 12), total: 12, summary: '' });
            send('delta', { text: words[i % words.length] });
            i++;
        }, 150);
        res.on('close', () => {
            clearInterval(timer);
            state.closed++;
        });
    });
    return new Promise(resolve => server.listen(port, '127.0.0.1', () => resolve({ state, close: () => server.close() })));
}

(async () => {
    const app = await startApp();
    const port = Number(process.env.E2E_PORT || 5099) + 700;
    const upstream = await streamServer(port);
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const errors = await openEditor(page, app.url);
        const log = await mockAgent(page, { stream: `http://127.0.0.1:${port}/stream` });
        await openAgent(page);
        await sendText(page, 'Fix typos slowly');
        await page.waitForSelector('.pa-tool.running');
        check(true, 'running tool chip appears while streaming');
        await page.waitForFunction(() => (document.querySelector('.pa-msg.assistant.streaming .pa-md')?.textContent || '').split(' ').length >= 4);
        check(await page.$('.pa-send.stop') !== null, 'send button turns into Stop while streaming');
        check(await page.$eval('.pa-input', el => el.disabled), 'input is disabled while a turn runs');
        check(/^\d+\/12$/.test(await page.textContent('.pa-tool.running .pa-tool-count')) && await page.$('.pa-tool.running .pa-tool-bar') !== null, 'tool progress shows done/total and a bar');
        check(await page.$eval('.pa-msg.assistant', el => el.getAttribute('aria-busy')) === 'true', 'streaming bubble is aria-busy');
        check(await page.$eval('.pa-log', el => el.getAttribute('role') === 'log' && el.getAttribute('aria-live') === 'polite'), 'message list is a polite live log');
        const partial = await page.textContent('.pa-msg.assistant .pa-md');
        check(partial.startsWith('Reading the page'), 'deltas stream into the assistant bubble');
        await page.click('.pa-send');
        await idle(page);
        check(log.stops === 1, 'Stop posts to the stop endpoint');
        await page.waitForFunction(() => document.querySelector('.pa-note')?.textContent.length > 0);
        check(await page.textContent('.pa-note') !== '', 'stopped note is shown');
        await page.waitForTimeout(200);
        check(upstream.state.closed === 1, 'the stream connection is aborted');
        const frozen = await page.textContent('.pa-msg.assistant .pa-md');
        await page.waitForTimeout(600);
        check(frozen === await page.textContent('.pa-msg.assistant .pa-md'), 'no more text arrives after Stop');
        check(await page.$('.pa-send.stop') === null && !(await page.$eval('.pa-send', el => el.disabled)), 'Send is available again');
        check(await page.$eval('.pa-msg.assistant', el => el.getAttribute('aria-busy')) === 'false', 'bubble is no longer busy');
        check(await page.$('.pa-typing') === null, 'typing skeleton is gone');
        check(await page.$('.pa-tool.running') === null && await page.$('.pa-tool.stopped') !== null, 'running tool chip switches to stopped');

        await page.fill('.pa-input', 'line one');
        await page.press('.pa-input', 'Shift+Enter');
        await page.type('.pa-input', 'line two');
        check(await page.$eval('.pa-input', el => el.value) === 'line one\nline two', 'Shift+Enter inserts a newline');
        check(log.messages.length === 1, 'Shift+Enter does not send');

        await page.evaluate(() => {
            const logEl = document.querySelector('.pa-log');
            for (let i = 0; i < 30; i++) logEl.insertAdjacentHTML('beforeend', '<p class="pa-note">filler</p>');
            logEl.scrollTop = 0;
            logEl.dispatchEvent(new Event('scroll'));
        });
        check(await page.$('.pa-jump:not([hidden])') !== null, 'jump-to-latest appears when scrolled up');
        await page.click('.pa-jump');
        check(await page.$eval('.pa-log', el => el.scrollHeight - el.scrollTop - el.clientHeight < 2), 'jump scrolls to the bottom');
        check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    } finally {
        await browser.close();
        upstream.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { ROOT, startApp, openEditor, check } = require('./helpers');

const PYTHON = process.env.E2E_PYTHON || path.join(ROOT, '.venv', 'bin', 'python');
const PAGES = 2500;

function bigPdf() {
    const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'wp3-')), 'big.pdf');
    execFileSync(PYTHON, ['-c', `
import sys, fitz
doc = fitz.open()
for i in range(${PAGES}):
    doc.new_page().insert_text((50, 60), '\\n'.join(f'Line {j} of page {i} lorem ipsum dolor sit amet' for j in range(40)), fontsize=11)
doc.save(sys.argv[1], garbage=3, deflate=True)
`, file]);
    return file;
}

async function openFile(page, url, file) {
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`${url}/pdf`);
    await page.setInputFiles('#pdfInput', file);
    await page.waitForSelector('.tool-card[data-tool="edit"]');
    await page.click('.tool-card[data-tool="edit"]');
    await page.waitForSelector('#pdfEditor:not(.hidden) .pe-page');
    await page.waitForFunction(() => typeof PdfEditor !== 'undefined' && PdfEditor.bridge.session()?.digest);
    return errors;
}

function record(page, kind) {
    return page.evaluate(kind => {
        window.__wp3 = [];
        PdfProgress.onTask(kind, task => window.__wp3.push(JSON.parse(JSON.stringify(task))));
    }, kind);
}

async function search(page, query) {
    if (!await page.isVisible('#peSheet [data-find="query"]')) {
        await page.click('.pe-tool[data-tool="redact"]');
        await page.click('[data-act="open-find"]');
        await page.waitForSelector('#peSheet [data-find="query"]');
    }
    await page.fill('#peSheet [data-find="query"]', query);
    await page.click('#peSheet [data-find="run"]');
}

async function fontsScenario(browser, url, viewport, colorScheme) {
    const context = await browser.newContext({ viewport, colorScheme });
    const page = await context.newPage();
    const states = [{ ready: false, done: 120, total: 480 }, { ready: false, done: 300, total: 480 }, { ready: true, done: 480, total: 480 }];
    let calls = 0;
    await page.route('**/api/pdf/edit/fonts/status', route => {
        const data = states[Math.min(calls++, states.length - 1)];
        return route.fulfill({ contentType: 'application/json', body: JSON.stringify({ success: true, data, error: null }) });
    });
    await page.addInitScript(() => {
        window.__fonts = [];
        document.addEventListener('DOMContentLoaded', () => PdfProgress.onTask('fonts', task => window.__fonts.push(JSON.parse(JSON.stringify(task)))));
    });
    const errors = await openEditor(page, url);
    await page.waitForFunction(() => window.__fonts.some(task => task.status === 'done'), null, { timeout: 10000 });
    const events = await page.evaluate(() => window.__fonts);
    check(events[0].title === 'Preparing system fonts… 120/480' && events[0].detail.total === 480, `fonts task shows scanned files (${events[0].title})`);
    check(events.some(task => task.progress === 300 / 480), 'fonts task follows the index');
    check(events[events.length - 1].status === 'done' && new Set(events.map(task => task.id)).size === 1, 'fonts task finishes when the index is ready');
    const polls = calls;
    await page.waitForTimeout(1500);
    check(calls === polls, 'font status polling stops once ready');
    check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    await context.close();
}

(async () => {
    const app = await startApp();
    const browser = await chromium.launch();
    const file = bigPdf();
    try {
        for (const { theme, viewport } of [
            { theme: 'dark', viewport: { width: 1280, height: 900 } },
            { theme: 'light', viewport: { width: 820, height: 1180 } }
        ]) {
            console.log(`# search ${theme} ${viewport.width}px`);
            const context = await browser.newContext({ viewport, colorScheme: theme });
            const page = await context.newPage();
            const errors = await openFile(page, app.url, file);
            const fileId = (await page.evaluate(() => PdfEditor.bridge.session())).fileId;
            await record(page, 'search');
            const partial = page.evaluate(async fileId => {
                const seen = [];
                const until = Date.now() + 20000;
                while (Date.now() < until) {
                    const res = await fetch(`/api/pdf/edit/tasks?file_id=${fileId}`).then(r => r.json());
                    const task = res.data.tasks.find(item => item.kind === 'search');
                    if (task) seen.push({ status: task.status, done: task.detail.done, total: task.detail.total });
                    if (task && task.status !== 'running' && task.status !== 'queued') break;
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                return seen;
            }, fileId);
            await search(page, 'zebra');
            await page.waitForFunction(() => window.__wp3.some(task => task.id.startsWith('local_') && task.status === 'done'), null, { timeout: 30000 });
            const seen = await partial;
            const running = seen.filter(item => item.status === 'running' && item.done > 0 && item.done < item.total);
            check(running.length > 0, `server search task reports pages while running (${running.map(item => item.done).join(', ')})`);
            check(seen[seen.length - 1].status === 'done' && seen[seen.length - 1].done === PAGES, `server search task ends at ${PAGES}/${PAGES}`);
            const local = (await page.evaluate(() => window.__wp3)).filter(task => task.id.startsWith('local_'));
            check(local[0].titleKey === 'pe_act_search' && local[local.length - 1].status === 'done', 'search shows a task in the activity feed');
            check(local.some(task => task.server_id && task.detail.total === PAGES && task.progress > 0 && task.progress < 1), 'local search task mirrors server page progress');

            await record(page, 'search');
            await search(page, 'zebra');
            await page.waitForFunction(() => window.__wp3.some(task => task.id.startsWith('local_') && task.server_id && task.status === 'running'), null, { timeout: 20000 });
            await page.evaluate(() => PdfActivityHooks.active().find(item => item.kind === 'search').cancel());
            await page.waitForFunction(() => window.__wp3.some(task => task.id.startsWith('local_') && task.status !== 'running'), null, { timeout: 20000 });
            const last = (await page.evaluate(() => window.__wp3)).filter(task => task.id.startsWith('local_')).pop();
            check(last.status === 'cancelled' && last.detail.done < PAGES, `cancelling a long search stops it on the server at ${last.detail.done}/${PAGES}`);
            check(errors.length === 0, `no page errors (${errors.join('; ')})`);
            await context.close();
        }
        console.log('# fonts');
        await fontsScenario(browser, app.url, { width: 1280, height: 900 }, 'dark');
        await fontsScenario(browser, app.url, { width: 390, height: 844 }, 'light');
    } finally {
        await browser.close();
        app.stop();
        fs.rmSync(path.dirname(file), { recursive: true, force: true });
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

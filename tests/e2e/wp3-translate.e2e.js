const { chromium } = require('playwright');
const { startApp, startFakeLm, openEditor, check } = require('./helpers');

const port = Number(process.env.FAKE_LM_PORT || 1303);

async function record(page) {
    await page.evaluate(() => {
        window.__wp3 = [];
        PdfProgress.onTask('translate', task => window.__wp3.push(JSON.parse(JSON.stringify(task))));
    });
}

async function openTranslate(page) {
    if (await page.isVisible('#peTranslateBtn')) await page.click('#peTranslateBtn');
    else {
        await page.click('#peMoreBtn');
        await page.click('#peSheet [data-menu="translate"]');
    }
    await page.waitForSelector('#peSheet button[data-translate="run"]:not([disabled])');
}

const localEvents = page => page.evaluate(() => window.__wp3.filter(task => task.id.startsWith('local_')));
const lastLocal = async page => (await localEvents(page)).pop();

(async () => {
    const lm = await startFakeLm({ port });
    const app = await startApp({ env: lm.env });
    const browser = await chromium.launch();
    try {
        for (const { theme, viewport } of [
            { theme: 'dark', viewport: { width: 1280, height: 900 } },
            { theme: 'light', viewport: { width: 390, height: 844 } }
        ]) {
            console.log(`# ${theme} ${viewport.width}px`);
            const context = await browser.newContext({ viewport, colorScheme: theme });
            const page = await context.newPage();
            const errors = await openEditor(page, app.url);
            await record(page);
            await page.route('**/api/pdf/edit/translate', async route => {
                await new Promise(resolve => setTimeout(resolve, 250));
                await route.continue();
            });
            await openTranslate(page);
            await page.click('#peSheet button[data-translate="run"]');
            await page.waitForFunction(() => window.__wp3.some(task => task.id.startsWith('local_') && task.status === 'done'), null, { timeout: 30000 });
            const events = await localEvents(page);
            const final = events[events.length - 1];
            check(final.status === 'done' && final.progress === 1, 'document translation task reaches 100 %');
            check(final.detail.done === 5 && final.detail.total === 5, 'task counts all five pages');
            check(final.titleKey === 'pe_act_translate' && /5\/5/.test(final.title), `task has a translated title (${final.title})`);
            const progress = events.map(task => task.progress).filter(value => typeof value === 'number');
            check(progress.every((value, i) => i === 0 || value >= progress[i - 1]), 'progress grows monotonically');
            check(events.some(task => typeof task.detail.eta_s === 'number' && task.detail.eta_s > 0), 'ETA is computed from seconds per page');
            check(new Set(events.map(task => task.id)).size === 1, 'one local task for the whole document');
            const server = await page.evaluate(async fileId => {
                const res = await fetch(`/api/pdf/edit/tasks?file_id=${fileId}`).then(r => r.json());
                return res.data.tasks.filter(task => task.kind === 'translate');
            }, (await page.evaluate(() => PdfEditor.bridge.session())).fileId);
            check(server.length === 5 && server.every(task => task.status === 'done' && task.stage === 'ops'), 'server keeps a per-page task with stages');
            check((await page.evaluate(() => PdfEditor.bridge.ops())).length > 0, 'translation ops were applied');

            await page.evaluate(() => { window.__wp3 = []; });
            await openTranslate(page);
            await page.click('#peSheet button[data-translate="run"]');
            await page.waitForFunction(() => window.__wp3.some(task => task.id.startsWith('local_') && task.detail.done >= 1));
            const running = await lastLocal(page);
            check(running.status === 'running' && running.detail.done < 5, 'running task is listed');
            const cancelled = await page.evaluate(() => {
                const task = PdfActivityHooks.active().find(item => item.kind === 'translate');
                return typeof task?.cancel === 'function' && (task.cancel(), true);
            });
            check(cancelled, 'activity task exposes cancel');
            await page.waitForFunction(() => window.__wp3.some(task => task.id.startsWith('local_') && task.status === 'cancelled'), null, { timeout: 15000 });
            const stopped = await lastLocal(page);
            check(stopped.status === 'cancelled' && stopped.detail.done < 5, `cancel from the activity task stops the loop at ${stopped.detail.done}/5`);
            await page.waitForFunction(() => !document.querySelector('#peSheet [data-translate="stop"]'));

            await page.evaluate(() => { window.__wp3 = []; });
            await openTranslate(page);
            await page.click('#peSheet button[data-translate="run"]');
            await page.waitForSelector('#peSheet [data-translate="stop"]');
            await page.waitForFunction(() => window.__wp3.some(task => task.id.startsWith('local_') && task.detail.done >= 1));
            await page.click('#peSheet [data-translate="stop"]');
            await page.waitForFunction(() => window.__wp3.some(task => task.id.startsWith('local_') && task.status !== 'running'), null, { timeout: 15000 });
            const sheetStopped = await lastLocal(page);
            check(sheetStopped.status === 'cancelled' && sheetStopped.detail.done < 5, 'Stop in the sheet cancels the task');
            check(errors.length === 0, `no page errors (${errors.join('; ')})`);
            await context.close();
        }
    } finally {
        await browser.close();
        app.stop();
        lm.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

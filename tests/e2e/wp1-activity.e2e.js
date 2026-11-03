const path = require('path');
const { chromium, devices } = require('playwright');
const { startApp, openEditor, check } = require('./helpers');

const SHOTS = process.env.E2E_SHOTS || '';

function drive(page, body) {
    return page.evaluate(async payload => {
        const res = await fetch('/api/pdf/edit/tasks/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
        return (await res.json()).data;
    }, body);
}

function fileId(page) {
    return page.evaluate(() => PdfEditor.bridge.session().fileId);
}

async function shot(page, name) {
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${name}.png`) });
}

async function noOverflow(page) {
    return page.evaluate(() => {
        const wide = [...document.querySelectorAll('#pdfEditor .pe-top, #pdfEditor .pe-activity, #pdfEditor .pe-task-toast')]
            .filter(el => el.offsetParent !== null || getComputedStyle(el).position === 'fixed')
            .some(el => el.scrollWidth > el.clientWidth + 1 || el.getBoundingClientRect().right > window.innerWidth + 1 || el.getBoundingClientRect().left < -1);
        return document.documentElement.scrollWidth <= window.innerWidth && !wide;
    });
}

async function desktop(browser, app) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    const errors = await openEditor(page, app.url);
    check(await page.evaluate(() => typeof io !== 'undefined'), 'socket.io client is loaded');
    await page.waitForFunction(() => appState.socket?.connected);
    check(await page.isVisible('#peActivityBtn'), 'activity button is shown');
    check(await page.isHidden('#peActivityBtn .pe-badge'), 'badge is hidden without tasks');

    const polls = [];
    page.on('request', req => req.url().includes('/api/pdf/edit/tasks?') && polls.push(Date.now()));
    const id = await fileId(page);
    const { task } = await drive(page, { kind: 'ocr', file_id: id, page: 1, stage: 'detect', progress: 0.3, detail: { done: 3, total: 10, eta_s: 12 } });
    await page.waitForFunction(() => document.querySelector('#peActivityBtn .pe-badge').textContent === '1');
    check(true, 'badge counts the running task');
    check(await page.isVisible('.pe-progress-strip:not(.hidden) .pe-progress-strip-fill'), 'foreground strip appears under the header');
    await page.waitForFunction(() => Math.abs(parseFloat(document.querySelector('.pe-progress-strip-fill').style.width) - 30) < 1);
    check(true, 'strip shows 30%');

    await page.click('#pePagesBtn');
    await page.waitForSelector('.pe-thumb[data-id="1"] .pe-thumb-ring');
    check(await page.$$eval('.pe-thumb-ring', els => els.length) === 1, 'only the task page thumbnail has a ring');
    await page.evaluate(() => PdfEditor.bridge.apply([{ type: 'page', action: 'rotate', page: 3, angle: 90 }], { label: 'rotate' }));
    await page.waitForSelector('.pe-thumb[data-id="1"] .pe-thumb-ring');
    check(true, 'ring survives a thumbnail re-render');

    await page.click('#peActivityBtn');
    await page.waitForSelector('#peActivity:not(.hidden) .pe-task');
    const item = await page.$eval('.pe-task', el => ({
        title: el.querySelector('.pe-task-title').textContent,
        page: el.querySelector('.pe-task-page').textContent,
        stage: el.querySelector('.pe-task-stage').textContent,
        info: el.querySelector('.pe-task-info').textContent
    }));
    check(item.title === 'Text recognition (OCR)' && item.page === 'Page 2', `item shows title and page (${item.title}, ${item.page})`);
    check(item.stage === 'Finding text lines', `item shows OCR stage (${item.stage})`);
    check(item.info.includes('3 of 10') && item.info.includes('about 12 s left'), `item shows steps and ETA (${item.info})`);
    await page.waitForTimeout(250);
    await shot(page, 'desktop-center');

    polls.length = 0;
    for (let step = 4; step <= 8; step++) await drive(page, { task_id: task.id, progress: step / 10, detail: { done: step, total: 10 } });
    await page.waitForFunction(() => Math.abs(parseFloat(document.querySelector('.pe-progress-strip-fill').style.width) - 80) < 1);
    const ring = await page.$eval('.pe-ring-arc', el => parseFloat(el.style.strokeDashoffset));
    check(Math.abs(ring - 20) < 1, `thumbnail ring follows progress (${ring})`);
    await page.waitForTimeout(2500);
    check(polls.length <= 1, `socket updates without polling (${polls.length} GETs in 2.5 s)`);

    await page.click('.pe-task[data-task="' + task.id + '"] .pe-task-cancel');
    await page.waitForSelector(`.pe-task.cancelled[data-task="${task.id}"]`);
    check((await drive(page, { task_id: task.id })).cancelled, 'cancel reaches the server task');
    check(await page.isHidden('#peActivityBtn .pe-badge'), 'badge clears after cancel');
    check(await page.isHidden('.pe-progress-strip-fill'), 'strip hides without running tasks');
    check(await page.$$eval('.pe-thumb-ring', els => els.length) === 0, 'ring removed after cancel');

    await page.keyboard.press('Escape');
    check(await page.isHidden('#peActivity'), 'Escape closes the activity center');
    await page.click('#pePanelClose').catch(() => page.click('#pePagesBtn'));

    const second = (await drive(page, { kind: 'ocr', file_id: id, page: 3, stage: 'recognize', progress: 0.5 })).task;
    await page.waitForFunction(() => document.querySelector('#peActivityBtn .pe-badge').textContent === '1');
    await drive(page, { task_id: second.id, finish: 'done' });
    await page.waitForSelector('.pe-task-toast:not(.hidden)');
    const toast = await page.textContent('.pe-task-toast');
    check(toast.includes('Text recognition (OCR) finished') && toast.includes('Page 4'), `done toast names task and page (${toast.trim().replace(/\s+/g, ' ')})`);
    await page.waitForTimeout(250);
    await shot(page, 'desktop-toast');
    await page.click('.pe-task-toast [data-toast="show"]');
    await page.waitForTimeout(900);
    const visible = await page.evaluate(() => {
        const rect = document.querySelectorAll('.pe-page')[3].getBoundingClientRect();
        return rect.top < window.innerHeight && rect.bottom > 0;
    });
    check(visible && await page.isHidden('.pe-task-toast'), 'Show scrolls to the page and dismisses the toast');

    const local = await page.evaluate(() => {
        let stopped = false;
        const handle = PdfProgress.local('translate', { total: 4, cancel: () => { stopped = true; } });
        handle.update({ detail: { done: 1, total: 4 } });
        window.__local = { handle, stopped: () => stopped };
        return handle.task.id;
    });
    await page.click('#peActivityBtn');
    await page.waitForSelector(`.pe-task[data-task="${local}"] .pe-task-cancel:not([hidden])`);
    check((await page.textContent(`.pe-task[data-task="${local}"] .pe-task-info`)).includes('1 of 4'), 'local task shows steps');
    await page.click(`.pe-task[data-task="${local}"] .pe-task-cancel`);
    check(await page.evaluate(() => window.__local.stopped() && window.__local.handle.cancelled()), 'cancelling a local task calls its cancel callback');
    await page.click('[data-activity="close"]');

    for (const lang of ['pl', 'de']) {
        await page.evaluate(code => i18n.setLanguage(code), lang);
        await page.click('#peActivityBtn');
        const title = await page.textContent(`.pe-task[data-task="${second.id}"] .pe-task-title`);
        check(title !== 'Text recognition (OCR)' && !title.startsWith('pe_'), `${lang} title is translated (${title})`);
        await page.click('[data-activity="close"]');
    }
    await page.evaluate(() => i18n.setLanguage('en'));
    check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    return { context, page };
}

async function linkedTasks(browser, app) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    const errors = await openEditor(page, app.url);
    const server = (await drive(page, { kind: 'translate', file_id: await fileId(page), page: 2, progress: 0.5 })).task;
    await page.waitForFunction(id => PdfProgress.get(id), server.id);
    await page.evaluate(serverId => {
        window.__stopped = false;
        const handle = PdfProgress.local('translate', { titleKey: 'pe_task_translate', title: 'Translating document… 1/5', total: 5, cancel: () => { window.__stopped = true; } });
        handle.update({ server_id: serverId, stageLabel: 'Translating', detail: { done: 1, total: 5 }, progress: 0.2 });
        window.__linked = handle;
    }, server.id);
    await page.click('#peActivityBtn');
    const local = await page.evaluate(() => window.__linked.task.id);
    await page.waitForSelector(`.pe-task[data-task="${local}"]`);
    check(await page.$(`.pe-task[data-task="${server.id}"]`) === null, 'server task linked by server_id is not listed twice');
    check(await page.textContent('#peActivityBtn .pe-badge') === '1', 'badge counts the linked pair once');
    check(await page.textContent(`.pe-task[data-task="${local}"] .pe-task-title`) === 'Translating document… 1/5', 'title comes from task.title');
    check(await page.textContent(`.pe-task[data-task="${local}"] .pe-task-stage`) === 'Translating', 'stage comes from task.stageLabel');
    await page.click('#pePagesBtn');
    await page.waitForSelector('.pe-thumb[data-id="2"] .pe-thumb-ring');
    check(true, 'hidden server task still rings its page thumbnail');
    check(await page.isHidden('#peActivity'), 'clicking outside closes the popover');
    await page.click('#peActivityBtn');
    await page.click(`.pe-task[data-task="${local}"] .pe-task-cancel`);
    await page.waitForSelector(`.pe-task.cancelled[data-task="${local}"]`);
    check(await page.evaluate(() => window.__stopped && typeof window.__linked.task.cancel === 'function'), 'cancel calls the function on the local task object');
    await drive(page, { task_id: server.id, finish: 'done' });
    await page.waitForTimeout(400);
    check(await page.isHidden('.pe-task-toast'), 'translate completion does not duplicate the core toast');
    check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    await context.close();
}

async function isolation(browser, app, first) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
    const page = await context.newPage();
    await openEditor(page, app.url);
    await page.waitForFunction(() => appState.socket?.connected);
    await page.evaluate(() => {
        window.__events = 0;
        appState.socket.on('editor_task', () => window.__events++);
    });
    const id = await fileId(first.page);
    const { task } = await drive(first.page, { kind: 'save', file_id: id, progress: 0.2 });
    await first.page.waitForSelector(`.pe-task[data-task="${task.id}"]`, { state: 'attached' }).catch(() => null);
    await first.page.waitForFunction(() => document.querySelector('#peActivityBtn .pe-badge').textContent === '1');
    await page.waitForTimeout(1200);
    check(await page.evaluate(() => window.__events) === 0, 'second context receives no socket events of the first');
    check(await page.isHidden('#peActivityBtn .pe-badge'), 'second context badge stays empty');
    const listed = await page.evaluate(() => fetch('/api/pdf/edit/tasks').then(r => r.json()).then(r => r.data.tasks.length));
    check(listed === 0, 'second context lists no tasks of the first');
    const cancelled = await page.evaluate(taskId => fetch(`/api/pdf/edit/tasks/${taskId}/cancel`, { method: 'POST' }).then(r => r.json()).then(r => r.data.cancelled), task.id);
    check(!cancelled, 'second context cannot cancel the first one\'s task');
    await drive(first.page, { task_id: task.id, finish: 'done' });
    await context.close();
}

async function phone(browser, app, theme, landscape = false) {
    const device = devices['iPhone 13'];
    const options = landscape ? { ...device, viewport: { width: device.viewport.height, height: device.viewport.width } } : device;
    const context = await browser.newContext({ ...options, reducedMotion: landscape ? 'reduce' : 'no-preference' });
    await context.addInitScript(value => localStorage.setItem('theme-preference', value), theme);
    const page = await context.newPage();
    const errors = await openEditor(page, app.url, 'pe_test.pdf', { touch: true });
    const label = `${landscape ? 'landscape' : 'portrait'} ${theme}`;
    check(await page.evaluate(() => document.documentElement.dataset.theme) === theme, `${label}: theme applied`);
    const compact = await page.evaluate(() => PdfEditor.bridge.compact());
    if (compact) check(await page.isHidden('#peActivityBtn'), `${label}: idle activity button hidden on phone`);
    const { task } = await drive(page, { kind: 'ocr', file_id: await fileId(page), page: 0, stage: 'render', progress: null });
    await page.waitForSelector('#peActivityBtn.busy');
    check(await page.isVisible('#peActivityBtn'), `${label}: busy activity button shown`);
    check(await noOverflow(page), `${label}: header has no horizontal overflow`);
    if (compact) {
        await page.tap('#peMoreBtn');
        await page.tap('[data-menu="ext:activity"]');
    } else {
        await page.tap('#peActivityBtn');
    }
    await page.waitForSelector('#peActivity:not(.hidden) .pe-task');
    await page.waitForTimeout(350);
    const box = await page.$eval('#peActivity', el => {
        const rect = el.getBoundingClientRect();
        return { bottom: rect.bottom, left: rect.left, width: rect.width, bg: getComputedStyle(el).backgroundColor };
    });
    const viewport = page.viewportSize();
    if (compact) check(Math.abs(box.bottom - viewport.height) < 2 && box.left === 0 && Math.abs(box.width - viewport.width) < 1, `${label}: center opens as a bottom sheet`);
    const target = await page.$eval('.pe-task-cancel', el => el.getBoundingClientRect().height);
    check(target >= 44, `${label}: cancel target is at least 44 px (${target})`);
    check(await page.$eval('.pe-task-fill', el => el.classList.contains('indeterminate')), `${label}: unknown progress is indeterminate`);
    check(await noOverflow(page), `${label}: center has no horizontal overflow`);
    if (landscape) check(await page.$eval('.pe-task-fill', el => getComputedStyle(el).animationName === 'none'), `${label}: reduced motion stops the indeterminate animation`);
    await shot(page, `phone-${landscape ? 'landscape' : 'portrait'}-${theme}`);
    if (compact) await page.tap('.pe-activity-backdrop', { position: { x: 20, y: 20 } });
    else await page.tap('[data-activity="close"]');
    check(await page.isHidden('#peActivity'), `${label}: center closes`);
    await drive(page, { task_id: task.id, finish: 'done' });
    await page.waitForSelector('.pe-task-toast:not(.hidden)');
    check(await noOverflow(page), `${label}: toast has no horizontal overflow`);
    await shot(page, `phone-toast-${landscape ? 'landscape' : 'portrait'}-${theme}`);
    check(errors.length === 0, `${label}: no page errors (${errors.join('; ')})`);
    return { context, bg: box.bg };
}

(async () => {
    const app = await startApp({ env: { OMNICONV_TEST_ROUTES: '1' } });
    const browser = await chromium.launch();
    try {
        const first = await desktop(browser, app);
        await isolation(browser, app, first);
        await first.context.close();
        await linkedTasks(browser, app);
        const dark = await phone(browser, app, 'dark');
        const light = await phone(browser, app, 'light');
        check(dark.bg !== light.bg, 'sheet background follows the theme');
        await dark.context.close();
        await light.context.close();
        const landscape = await phone(browser, app, 'dark', true);
        await landscape.context.close();
    } finally {
        await browser.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

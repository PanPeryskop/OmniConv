const { chromium, devices } = require('playwright');
const { startApp, startFakeLm, openEditor, check } = require('./helpers');

async function openTranslate(page, touch) {
    if (await page.isVisible('#peTranslateBtn')) await page.click('#peTranslateBtn');
    else {
        await page[touch ? 'tap' : 'click']('#peMoreBtn');
        await page[touch ? 'tap' : 'click']('#peSheet [data-menu="translate"]');
    }
    await page.waitForSelector('#peSheet button[data-translate="run"]:not([disabled])');
}

async function goTo(page, id) {
    await page.evaluate(pageId => document.querySelector(`.pe-page[data-page="${pageId}"]`).scrollIntoView({ block: 'start' }), id);
    await page.waitForFunction(pageId => PdfEditor.bridge.session().current === pageId, id);
}

(async () => {
    const lm = await startFakeLm({ port: Number(process.env.FAKE_LM_PORT || 5296) });
    const app = await startApp({ port: Number(process.env.E2E_PORT || 5196), env: lm.env });
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const errors = await openEditor(page, app.url);
        await page.evaluate(() => {
            window.__tasks = [];
            PdfProgress.onTask('translate', task => window.__tasks.push(JSON.parse(JSON.stringify(task))));
        });
        await goTo(page, 2);
        await openTranslate(page, false);
        const scope = page.locator('#peSheet [data-act="translate-scope"]');
        check(await scope.count() === 2, 'sheet offers this page or the whole document');
        check(await page.getAttribute('#peSheet [data-act="translate-scope"][data-value="document"]', 'aria-pressed') === 'true', 'whole document stays the default');
        await page.click('#peSheet [data-act="translate-scope"][data-value="page"]');
        check(await page.getAttribute('#peSheet [data-act="translate-scope"][data-value="page"]', 'aria-pressed') === 'true', 'page scope can be picked');
        check((await page.textContent('#peSheet [data-act="translate-scope"][data-value="page"]')).includes('3'), 'page scope names the current page');
        check((await page.textContent('#peSheet button[data-translate="run"]')).trim() === 'Translate page', 'run button says it translates one page');

        await goTo(page, 3);
        check((await page.textContent('#peSheet [data-act="translate-scope"][data-value="page"]')).includes('4'), 'page scope follows scrolling');
        const requests = [];
        page.on('request', request => request.url().endsWith('/api/pdf/edit/translate') && requests.push(request.postDataJSON().page));
        await page.click('#peSheet button[data-translate="run"]');
        await page.waitForFunction(() => PdfEditor.bridge.ops().length > 0, null, { timeout: 30000 });
        const ops = await page.evaluate(() => PdfEditor.bridge.ops());
        check(requests.length === 1 && requests[0] === 3, `only the current page is sent (${requests.join(',')})`);
        check(ops.length > 0 && ops.every(op => op.page === 3), 'translation ops land on that page only');
        check(new Set(ops.map(op => op.g)).size === 1, 'one undo step');
        const toast = await page.waitForSelector('.toast', { timeout: 5000 }).then(el => el.textContent()).catch(() => '');
        check(toast.includes('Page 4 translated'), `toast names the page (${toast.trim()})`);
        const titles = await page.evaluate(() => window.__tasks.filter(task => task.id.startsWith('local_')).map(task => task.title));
        check(titles.some(title => title === 'Translating page 4'), `activity shows the page (${[...new Set(titles)].join(' | ')})`);
        await page.evaluate(() => i18n.setLanguage('pl'));
        await openTranslate(page, false);
        check((await page.textContent('#peSheet [data-act="translate-scope"][data-value="page"]')).trim() === 'Ta strona (4)', 'Polish label');
        await page.evaluate(() => i18n.setLanguage('en'));
        check(errors.length === 0, `no page errors (${errors.join('; ')})`);

        for (const theme of ['dark', 'light']) {
            const context = await browser.newContext({ ...devices['iPhone 13'], colorScheme: theme });
            await context.addInitScript(value => localStorage.setItem('theme-preference', value), theme);
            const phone = await context.newPage();
            const phoneErrors = await openEditor(phone, app.url, 'pe_test.pdf', { touch: true });
            await openTranslate(phone, true);
            await phone.tap('#peSheet [data-act="translate-scope"][data-value="page"]');
            const boxes = await phone.$$eval('#peSheet [data-act="translate-scope"]', els => els.map(el => el.getBoundingClientRect().toJSON()));
            check(boxes.every(box => box.height >= 44 && box.left >= 0 && box.right <= 390), `${theme}: scope buttons are full-size touch targets`);
            check(await phone.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth), `${theme}: no horizontal overflow`);
            await phone.tap('#peSheet button[data-translate="run"]');
            await phone.waitForFunction(() => PdfEditor.bridge.ops().length > 0, null, { timeout: 30000 });
            check(await phone.evaluate(() => PdfEditor.bridge.ops().every(op => op.page === 0)), `${theme}: phone translates the first page only`);
            check(phoneErrors.length === 0, `${theme}: no page errors (${phoneErrors.join('; ')})`);
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

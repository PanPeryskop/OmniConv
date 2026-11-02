const { chromium } = require('playwright');
const { startApp, openEditor, check } = require('./helpers');

(async () => {
    const app = await startApp();
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const errors = await openEditor(page, app.url);
        const session = await page.evaluate(() => PdfEditor.bridge.session());
        check(session.order.length === 5 && session.base === 5, 'session exposes page order');
        const layout = await page.evaluate(() => PdfEditor.bridge.layout(0));
        check(layout.blocks.length > 0, 'layout() returns page blocks');
        const seen = await page.evaluate(() => new Promise(resolve => {
            PdfEditor.bridge.on('ops', payload => resolve(payload.ops.length));
            PdfEditor.bridge.apply([{ type: 'whiteout', page: 0, rect: [60, 400, 200, 440] }], { label: 'test' });
        }));
        check(seen === 1, 'apply() pushes ops and emits "ops"');
        check((await page.textContent('#peStatus')).includes('1'), 'status shows one change');
        await page.evaluate(() => PdfEditor.bridge.focus(0, [[60, 100, 300, 140]], 'proposal'));
        check(await page.$$eval('.pe-focus', els => els.length) === 1, 'focus() highlights rects');
        await page.evaluate(() => PdfEditor.bridge.clearFocus());
        check(await page.$$eval('.pe-focus', els => els.length) === 0, 'clearFocus() removes highlight');
        const opened = await page.evaluate(() => PdfEditor.bridge.side(true));
        check(opened && await page.$eval('#peSide', el => !el.classList.contains('hidden')), 'side(true) opens the side panel');
        await page.keyboard.press('Control+z');
        await page.waitForTimeout(300);
        check((await page.evaluate(() => PdfEditor.bridge.ops())).length === 0, 'undo removes the applied group');
        check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    } finally {
        await browser.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

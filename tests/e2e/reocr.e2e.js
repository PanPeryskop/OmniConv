const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium, devices } = require('playwright');
const { ROOT, FIXTURES, startApp, openEditor, check } = require('./helpers');
const { textOp } = require('./wp6-mock');

const PYTHON = process.env.E2E_PYTHON || path.join(ROOT, '.venv', 'bin', 'python');
const OLD = 'Bledny tekst ze starego OCR';

function layeredScan() {
    const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'reocr-')), 'layered.pdf');
    execFileSync(PYTHON, ['-c', [
        'import sys, fitz',
        'out = fitz.open(sys.argv[1])',
        'page = out[0]',
        `for i in range(3): page.insert_text((80, 120 + i * 30), "${OLD} %d" % i, fontsize=12, render_mode=3)`,
        'out.insert_pdf(fitz.open(sys.argv[2]), from_page=0, to_page=0)',
        'out.save(sys.argv[3])'
    ].join('\n'), path.join(FIXTURES, 'pe_scan.pdf'), path.join(FIXTURES, 'pe_test.pdf'), file]);
    return path.relative(FIXTURES, file);
}

const pageText = (page, id) => page.evaluate(async pageId => {
    const data = await PdfEditor.bridge.layout(pageId);
    return (data?.blocks || []).flatMap(b => b.lines.flatMap(l => l.spans.map(s => s.t))).join(' ');
}, id);

async function settle(page, id, test, timeout = 40000) {
    const until = Date.now() + timeout;
    while (Date.now() < until) {
        const text = await pageText(page, id);
        if (test(text)) return text;
        await page.waitForTimeout(400);
    }
    return pageText(page, id);
}

(async () => {
    const fixture = layeredScan();
    const app = await startApp({ env: { PE_OCR_STEPS: 'tests.fakes.fake_ocr', PE_OCR_FAKE_DELAY: '0.3' } });
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const errors = await openEditor(page, app.url, fixture);
        await page.click('#pePagesBtn');
        await page.waitForSelector('.pe-thumb[data-id="0"]');
        check(await page.$('.pe-thumb[data-id="0"] [data-thumb="reocr"]') !== null, 'scan thumbnail offers recognizing text again');
        check(await page.$('.pe-thumb[data-id="1"] [data-thumb="reocr"]') === null, 'digital page thumbnail has no re-OCR action');
        check((await pageText(page, 0)).includes(OLD), 'page starts with the old hidden text layer');

        const block = (await page.evaluate(() => PdfEditor.bridge.layout(0))).blocks[0];
        await page.evaluate(op => PdfEditor.bridge.apply([op], { label: 'edit' }), textOp(0, block, 'Poprawka uzytkownika'));
        check((await settle(page, 0, text => text.includes('Poprawka'))).includes('Poprawka'), 'user edit is visible');
        const before = await page.evaluate(() => PdfEditor.bridge.ops().length);

        let message = '';
        page.once('dialog', dialog => {
            message = dialog.message();
            dialog.dismiss();
        });
        await page.click('.pe-thumb[data-id="0"] [data-thumb="reocr"]');
        for (let i = 0; i < 50 && !message; i++) await page.waitForTimeout(100);
        await page.waitForTimeout(200);
        check(/1 earlier text change/.test(message), `confirmation names the replaced edits (${message})`);
        check(await page.evaluate(() => PdfEditor.bridge.ops().length) === before, 'dismissing the confirmation changes nothing');

        page.once('dialog', dialog => dialog.accept());
        await page.click('.pe-thumb[data-id="0"] [data-thumb="reocr"]');
        await page.waitForFunction(n => PdfEditor.bridge.ops().length === n + 1, before);
        const last = await page.evaluate(() => PdfEditor.bridge.ops().pop());
        check(last.type === 'ocr' && last.force === true && last.page === 0 && last.retry > 0, 'forced OCR op is added');
        await page.waitForSelector('.pe-page[data-page="0"] .pe-ocr', { timeout: 15000 }).catch(() => null);
        const fresh = await settle(page, 0, text => text.includes('Recognized line'));
        check(fresh.includes('Recognized line') && !fresh.includes(OLD), 'text layer is rebuilt from the scan');
        check(!fresh.includes('Poprawka'), 'earlier edit on that page is replaced');

        await page.keyboard.press('Control+z');
        await page.waitForFunction(n => PdfEditor.bridge.ops().length === n, before);
        const restored = await settle(page, 0, text => text.includes('Poprawka'));
        check(restored.includes('Poprawka'), 'undo brings the earlier edit back');

        await page.click('#pePagesBtn');
        await page.waitForSelector('#pePanel.hidden', { state: 'attached' });
        const pill = page.locator('.pe-page[data-page="0"] .pe-page-reocr');
        check(await pill.count() === 1, 'scan page has its own re-OCR button');
        check(await page.locator('.pe-page[data-page="1"] .pe-page-reocr').count() === 0, 'digital page has no re-OCR button');
        await page.mouse.move(5, 5);
        await page.waitForTimeout(250);
        check(await pill.evaluate(el => getComputedStyle(el).opacity) === '0', 'button stays out of the way until the page is hovered');
        const frame = await page.locator('.pe-page[data-page="0"]').boundingBox();
        await page.mouse.move(frame.x + frame.width / 2, frame.y + 40);
        await page.waitForTimeout(250);
        check(await pill.evaluate(el => getComputedStyle(el).opacity) === '1', 'hovering the page reveals the button');
        const label = await pill.textContent();
        check(label.trim() === 'Recognize text again', `button is labelled (${label.trim()})`);
        const count = await page.evaluate(() => PdfEditor.bridge.ops().length);
        page.once('dialog', dialog => dialog.accept());
        await pill.click();
        await page.waitForFunction(n => PdfEditor.bridge.ops().length === n + 1, count);
        check(await page.evaluate(() => { const op = PdfEditor.bridge.ops().pop(); return op.type === 'ocr' && op.force; }), 'page button starts recognition');
        check(await page.evaluate(() => PdfEditor.bridge.ops().filter(op => op.type === 'text').length) === 1, 'page button does not start a selection or remove edits');
        await page.evaluate(() => i18n.setLanguage('pl'));
        check((await pill.textContent()).trim() === 'Rozpoznaj tekst ponownie', 'button label follows the language');
        await page.evaluate(() => i18n.setLanguage('en'));
        check(errors.length === 0, `no page errors (${errors.join('; ')})`);

        const tablet = await browser.newContext({ ...devices['iPad Mini'] });
        const pad = await tablet.newPage();
        const padErrors = await openEditor(pad, app.url, fixture, { touch: true });
        const padPill = pad.locator('.pe-page[data-page="0"] .pe-page-reocr');
        await padPill.waitFor();
        await pad.waitForFunction(() => {
            const el = document.querySelector('.pe-page[data-page="0"] .pe-page-reocr');
            return el && !el.closest('.pe-page').classList.contains('loading') && getComputedStyle(el).opacity === '1';
        }, null, { timeout: 20000 });
        const padBox = await padPill.boundingBox();
        check(await padPill.evaluate(el => getComputedStyle(el).opacity) === '1' && padBox.height >= 40, 'tablet shows a touch-size button without hover');
        await padPill.tap();
        await pad.waitForFunction(() => PdfEditor.bridge.ops().some(op => op.type === 'ocr' && op.force));
        check(padErrors.length === 0, `tablet: no page errors (${padErrors.join('; ')})`);
        await tablet.close();

        for (const theme of ['dark', 'light']) {
            const context = await browser.newContext({ ...devices['iPhone 13'], colorScheme: theme });
            await context.addInitScript(value => localStorage.setItem('theme-preference', value), theme);
            const phone = await context.newPage();
            const phoneErrors = await openEditor(phone, app.url, fixture, { touch: true });
            check(await phone.locator('.pe-page[data-page="0"] .pe-page-reocr').evaluate(el => getComputedStyle(el).display) === 'none', `${theme}: phone keeps the page clean and uses the menu`);
            await phone.tap('#peMoreBtn');
            const entry = phone.locator('[data-menu="reocr"]');
            await entry.waitFor();
            const box = await entry.boundingBox();
            check(box.height >= 44 && box.x >= 0 && box.x + box.width <= 390, `${theme}: menu entry is a full-size touch target`);
            await entry.tap();
            await phone.waitForFunction(() => PdfEditor.bridge.ops().some(op => op.type === 'ocr' && op.force));
            check(true, `${theme}: menu entry starts recognition without a prompt when there are no edits`);
            const text = await settle(phone, 0, value => value.includes('Recognized line'));
            check(text.includes('Recognized line') && !text.includes(OLD), `${theme}: phone page is recognized again`);
            await phone.evaluate(() => { document.querySelector('#peScroll').scrollTop = 1e6; });
            await phone.waitForFunction(() => PdfEditor.bridge.session().current === 1);
            await phone.tap('#peMoreBtn');
            await phone.waitForSelector('[data-menu="ext:agent"]');
            check(await phone.$('[data-menu="reocr"]') === null, `${theme}: menu hides the entry on a digital page`);
            check(phoneErrors.length === 0, `${theme}: no page errors (${phoneErrors.join('; ')})`);
            await context.close();
        }
    } finally {
        await browser.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

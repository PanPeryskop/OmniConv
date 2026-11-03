const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium } = require('playwright');
const { ROOT, FIXTURES, startApp, openEditor, check } = require('./helpers');

const PYTHON = process.env.E2E_PYTHON || path.join(ROOT, '.venv', 'bin', 'python');
const SHOTS = process.env.E2E_SHOTS || fs.mkdtempSync(path.join(os.tmpdir(), 'wp2-shots-'));

function multiScan(pages) {
    const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'wp2-')), 'scans.pdf');
    execFileSync(PYTHON, ['-c', [
        'import sys, fitz',
        'src = fitz.open(sys.argv[1])',
        'out = fitz.open()',
        'for _ in range(int(sys.argv[3])): out.insert_pdf(src)',
        'out.save(sys.argv[2])'
    ].join('\n'), path.join(FIXTURES, 'pe_scan.pdf'), file, String(pages)]);
    return path.relative(FIXTURES, file);
}

async function until(fn, timeout = 30000, step = 150) {
    const end = Date.now() + timeout;
    while (Date.now() < end) {
        const value = await fn();
        if (value) return value;
        await new Promise(r => setTimeout(r, step));
    }
    throw new Error(`Timed out: ${fn}`);
}

const overlay = id => `.pe-page[data-page="${id}"] .pe-ocr`;

async function pageState(page, id) {
    return page.evaluate(pageId => {
        const el = document.querySelector(`.pe-page[data-page="${pageId}"]`);
        const ocr = el?.querySelector('.pe-ocr');
        return {
            boxes: ocr ? ocr.querySelectorAll('.pe-ocr-boxes i').length : 0,
            filled: ocr ? ocr.querySelectorAll('.pe-ocr-boxes i.done').length : 0,
            label: ocr?.querySelector('.pe-ocr-label')?.textContent || '',
            blocks: el ? el.querySelectorAll('.pe-block').length : 0,
            overlay: !!ocr
        };
    }, id);
}

async function recognizeAll(browser, url) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    const errors = await openEditor(page, url, multiScan(3));
    await page.evaluate(() => { document.querySelector('#peScroll').scrollTop = 1e6; });
    await until(() => page.evaluate(() => PdfOcrView.candidates().length >= 2));
    await page.evaluate(() => { document.querySelector('#peScroll').scrollTop = 0; });
    const notice = page.locator('.pe-ocr-notice:not([hidden])');
    await notice.waitFor();
    check((await notice.textContent()).includes('scanned pages'), 'recognize-all notice counts scanned pages');
    const candidates = await page.evaluate(() => PdfOcrView.candidates());
    await notice.locator('[data-ocr-all="run"]').click();
    await page.waitForFunction(n => PdfEditor.bridge.ops().filter(op => op.type === 'ocr').length >= n, candidates.length);
    const ops = await page.evaluate(() => PdfEditor.bridge.ops());
    const ocr = ops.filter(op => op.type === 'ocr');
    check(ocr.length === candidates.length && new Set(ocr.map(op => op.g)).size === 1, `notice applies ${candidates.length} ocr ops as one group`);
    check(await notice.count() === 0, 'notice hides after applying');

    const labels = new Set();
    let boxesBeforeText = false;
    await until(async () => {
        const state = await pageState(page, 0);
        if (state.label) labels.add(state.label);
        if (state.boxes > 0 && state.blocks === 0) boxesBeforeText = true;
        return state.blocks > 0 && !state.overlay;
    }, 90000, 120);
    const recognized = [...labels].filter(label => /Recognized \d+\/\d+ lines/.test(label));
    check(boxesBeforeText, 'overlay shows detected boxes before the text layer');
    check(recognized.length >= 1 && labels.size >= 3, `label updates through the stages (${[...labels].join(' | ')})`);
    check([...labels].some(label => label.includes('about')), 'label shows an ETA');
    check((await pageState(page, 0)).blocks > 0, 'page reloads with recognized text and the overlay is gone');
    const tasks = await page.evaluate(async () => (await fetch(`/api/pdf/edit/tasks?file_id=${PdfEditor.bridge.session().fileId}`).then(r => r.json())).data.tasks);
    check(tasks.filter(task => task.kind === 'ocr').length === candidates.length, 'every recognized page has its own OCR task');
    await until(async () => {
        const list = await page.evaluate(async () => (await fetch(`/api/pdf/edit/tasks?file_id=${PdfEditor.bridge.session().fileId}`).then(r => r.json())).data.tasks);
        return list.filter(task => task.kind === 'ocr').every(task => task.status === 'done');
    }, 90000, 500);
    check(true, 'off-screen pages finish in the background');
    const stored = await until(() => page.evaluate(() => JSON.parse(localStorage.getItem('pe_ocr_page_seconds') || '[]').length), 5000);
    check(stored >= 1, 'seconds per page stored for the ETA');
    check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    await page.close();
}

async function cancelAndRetry(browser, url) {
    const page = await browser.newPage({ viewport: { width: 1024, height: 1366 } });
    const errors = await openEditor(page, url, 'pe_scan.pdf');
    await page.evaluate(() => PdfEditor.bridge.apply([{ type: 'ocr', page: 0 }], { label: 'ocr' }));
    await until(async () => /Recognized/.test((await pageState(page, 0)).label), 60000);
    const before = await pageState(page, 0);
    await page.click(`${overlay(0)} [data-ocr="cancel"]`);
    await until(async () => (await pageState(page, 0)).label.includes('cancelled'));
    const fileId = await page.evaluate(() => PdfEditor.bridge.session().fileId);
    const list = () => page.evaluate(async id => (await fetch(`/api/pdf/edit/tasks?file_id=${id}`).then(r => r.json())).data.tasks.filter(t => t.kind === 'ocr'), fileId);
    await until(async () => (await list()).every(task => task.status === 'cancelled'));
    await page.waitForTimeout(6000);
    const after = await pageState(page, 0);
    const tasks = await list();
    check(tasks.length === 1 && tasks[0].status === 'cancelled', 'cancel stops the task and the next preview does not restart it');
    check(after.filled <= before.filled + 8 && after.blocks === 0, `no further batches and no text after cancel (${JSON.stringify([before, after])})`);
    check(await page.isVisible(`${overlay(0)} [data-ocr="retry"]`), 'cancelled overlay offers a retry');
    await page.click(`${overlay(0)} [data-ocr="retry"]`);
    await until(async () => (await pageState(page, 0)).blocks > 0, 90000);
    check((await list()).some(task => task.status === 'done'), 'retry recognizes the page');
    check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    await page.close();
}

async function phone(browser, url, theme, landscape) {
    const size = landscape ? { width: 844, height: 390 } : { width: 390, height: 844 };
    const context = await browser.newContext({ viewport: size, isMobile: true, hasTouch: true, deviceScaleFactor: 2 });
    await context.addInitScript(value => {
        localStorage.setItem('theme-preference', value);
        localStorage.setItem('lang', 'pl');
    }, theme);
    const page = await context.newPage();
    const errors = await openEditor(page, url, multiScan(2), { touch: true });
    await page.evaluate(() => PdfEditor.bridge.apply([{ type: 'ocr', page: 0 }], { label: 'ocr' }));
    await until(async () => (await pageState(page, 0)).boxes > 0, 60000);
    await until(async () => /Rozpoznano/.test((await pageState(page, 0)).label), 60000);
    const metrics = await page.evaluate(id => {
        const host = document.querySelector(`.pe-page[data-page="${id}"]`).getBoundingClientRect();
        const bar = document.querySelector(`.pe-page[data-page="${id}"] .pe-ocr-bar`).getBoundingClientRect();
        const button = document.querySelector(`.pe-page[data-page="${id}"] [data-ocr="cancel"]`).getBoundingClientRect();
        return {
            inside: bar.left >= host.left - 1 && bar.right <= host.right + 1 && bar.right <= window.innerWidth,
            button: button.height,
            overflow: document.documentElement.scrollWidth > window.innerWidth
        };
    }, 0);
    const label = landscape ? 'landscape' : 'portrait';
    check(metrics.inside && !metrics.overflow, `phone ${label} ${theme}: overlay bar fits the page`);
    check(metrics.button >= 44, `phone ${label} ${theme}: cancel is a 44 px target`);
    await page.screenshot({ path: path.join(SHOTS, `wp2-phone-${label}-${theme}.png`) });
    await page.click(`${overlay(0)} [data-ocr="cancel"]`);
    await until(async () => (await pageState(page, 0)).label.includes('anulowane'));
    check(true, `phone ${label} ${theme}: Polish labels and cancel`);
    check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    await context.close();
}

(async () => {
    const app = await startApp({ env: { PE_OCR_STEPS: 'tests.fakes.fake_ocr', PE_OCR_FAKE_DELAY: '1.6' } });
    const browser = await chromium.launch();
    try {
        await recognizeAll(browser, app.url);
        await cancelAndRetry(browser, app.url);
        await phone(browser, app.url, 'dark', false);
        await phone(browser, app.url, 'light', false);
        await phone(browser, app.url, 'light', true);
        console.log(`  screenshots in ${SHOTS}`);
    } finally {
        await browser.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium, devices } = require('playwright');
const { ROOT, startApp, check } = require('./helpers');

const PYTHON = process.env.E2E_PYTHON || path.join(ROOT, '.venv', 'bin', 'python');
const SHOTS = process.env.E2E_SHOTS || fs.mkdtempSync(path.join(os.tmpdir(), 'chapters-shots-'));

function makeBook(name, options) {
    const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'chapters-')), name);
    execFileSync(PYTHON, ['-c', `import sys, json\nfrom tests.test_pdf_chapters import book\nbook(sys.argv[1], **json.loads(sys.argv[2]))`, file, JSON.stringify(options)], { cwd: ROOT });
    return file;
}

function zipEntries(file) {
    return JSON.parse(execFileSync(PYTHON, ['-c', 'import sys, json, zipfile, fitz\nz = zipfile.ZipFile(sys.argv[1])\nprint(json.dumps([[n, fitz.open(stream=z.read(n), filetype="pdf").page_count] for n in sorted(z.namelist())]))', file], { cwd: ROOT }).toString());
}

async function openSplit(page, url, file, touch = false) {
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`${url}/pdf`);
    await page.setInputFiles('#pdfInput', file);
    const card = '.tool-card[data-tool="split"]';
    await page.waitForSelector(card);
    await page[touch ? 'tap' : 'click'](card);
    await page[touch ? 'tap' : 'click']('[data-group="splitMode"] .choice[data-value="chapters"]');
    await page.waitForSelector('#chapterList .chapter-item');
    return errors;
}

const parts = page => page.$$eval('#chapterList .chapter-item', items => items.map(item => ({
    title: item.querySelector('input').value,
    pages: item.querySelector('.chapter-pages').textContent
})));

(async () => {
    const app = await startApp({ port: Number(process.env.E2E_PORT || 5199) });
    const browser = await chromium.launch();
    const headings = makeBook('ksiazka.pdf', { style: 'keyword' });
    const marked = makeBook('zakladki.pdf', { style: 'none', bookmarks: true });
    try {
        const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: 'dark', acceptDownloads: true });
        await context.addInitScript(() => localStorage.setItem('theme-preference', 'dark'));
        const page = await context.newPage();
        const errors = await openSplit(page, app.url, headings);
        let list = await parts(page);
        check(list.length === 5, `five parts are detected (${list.length})`);
        check((await page.textContent('#chaptersStatus')).includes('Detected from headings: 5 parts'), 'status explains where the parts come from');
        check(list[1].title === 'Rozdzial 1 - Tytul rozdzialu 1' && list[1].pages.startsWith('Pages 3-5'), `chapter title and range (${list[1].title} / ${list[1].pages})`);
        check(await page.isHidden('#chaptersSource') && await page.isHidden('#chaptersLevel'), 'no bookmark controls without bookmarks');
        await page.screenshot({ path: path.join(SHOTS, 'chapters-desktop-dark.png'), fullPage: true });

        await page.fill('#chapterList [data-title="1"]', 'Wstep');
        await page.click('#chapterList [data-join="2"]');
        list = await parts(page);
        check(list.length === 4 && list[1].title === 'Wstep' && list[1].pages.startsWith('Pages 3-8'), 'joining merges the range into the previous part');
        await page.fill('#chapterAddPage', '1');
        await page.click('#chapterAdd');
        check(await page.isVisible('.chapter-add .field-error'), 'page 1 is rejected with a message');
        await page.fill('#chapterAddPage', '7');
        await page.press('#chapterAddPage', 'Enter');
        list = await parts(page);
        check(list.length === 5 && list[2].pages.startsWith('Pages 7-8') && await page.isHidden('.chapter-add .field-error'), 'a split can be added by page number');
        check(await page.evaluate(() => document.activeElement?.dataset.title === '2'), 'the new part is focused for naming');
        check((await page.textContent('#chaptersSummary')).includes('5 files'), 'summary counts the files');

        await page.click('#chapterList [data-view="11"]');
        await page.waitForSelector('#viewer:not(.hidden)');
        check((await page.textContent('#viewerCounter')).startsWith('12 /'), 'thumbnail opens the page preview');
        await page.keyboard.press('Escape');
        await page.waitForSelector('#viewer.hidden', { state: 'attached' });

        await page.click('#toolRun');
        await page.waitForSelector('#pdfResult:not(.hidden)', { timeout: 60000 });
        const [download] = await Promise.all([page.waitForEvent('download'), page.click('#pdfResultDownload')]);
        const saved = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'chapters-zip-')), 'parts.zip');
        await download.saveAs(saved);
        const entries = zipEntries(saved);
        check(entries.length === 5, `zip has five PDFs (${entries.map(e => e[0]).join(', ')})`);
        check(JSON.stringify(entries.map(e => e[1])) === JSON.stringify([2, 4, 2, 3, 3]), `page counts follow the edited splits (${entries.map(e => e[1]).join(',')})`);
        check(entries.some(([name]) => name.includes('Wstep')), 'edited name is used for the file');
        check(errors.length === 0, `no page errors (${errors.join('; ')})`);
        await context.close();

        const marks = await browser.newContext({ viewport: { width: 1280, height: 900 } });
        const bookmarks = await marks.newPage();
        const markErrors = await openSplit(bookmarks, app.url, marked);
        check((await parts(bookmarks)).length === 5 && (await bookmarks.textContent('#chaptersStatus')).includes('bookmarks'), 'bookmarks are used first');
        check(await bookmarks.isVisible('#chaptersLevel'), 'level switch appears for nested bookmarks');
        await bookmarks.click('#chaptersLevel [data-level="2"]');
        await bookmarks.waitForFunction(() => document.querySelectorAll('#chapterList .chapter-item').length === 6);
        check(await bookmarks.getAttribute('#chaptersLevel [data-level="2"]', 'aria-pressed') === 'true', 'subchapters split into six parts');
        await bookmarks.click('#chaptersSource');
        await bookmarks.waitForFunction(() => document.querySelector('#chaptersStatus').textContent.includes('headings') || document.querySelector('#chaptersStatus').textContent.includes('No chapters'));
        check(await bookmarks.isHidden('#chaptersLevel'), 'switching to headings hides the level switch');
        await bookmarks.evaluate(() => i18n.setLanguage('pl'));
        check((await bookmarks.textContent('#chaptersSource')).trim() === 'Użyj zakładek', 'Polish labels');
        check(markErrors.length === 0, `no page errors (${markErrors.join('; ')})`);
        await marks.close();

        for (const theme of ['dark', 'light']) {
            const phoneContext = await browser.newContext({ ...devices['iPhone 13'], colorScheme: theme });
            await phoneContext.addInitScript(value => localStorage.setItem('theme-preference', value), theme);
            const phone = await phoneContext.newPage();
            const phoneErrors = await openSplit(phone, app.url, headings, true);
            const layout = await phone.evaluate(() => {
                const width = document.documentElement.clientWidth;
                const items = [...document.querySelectorAll('#chapterList .chapter-item, #chapterList .icon-btn, #chapterList input')].map(el => el.getBoundingClientRect());
                const joins = [...document.querySelectorAll('#chapterList [data-join]')].map(el => el.getBoundingClientRect());
                const input = getComputedStyle(document.querySelector('#chapterList input')).fontSize;
                return {
                    overflow: document.documentElement.scrollWidth > width,
                    outside: items.some(r => r.left < -1 || r.right > width + 1),
                    small: joins.some(r => r.width < 44 || r.height < 44),
                    input
                };
            });
            check(!layout.overflow && !layout.outside, `${theme}: parts fit the phone width`);
            check(!layout.small, `${theme}: join buttons are full touch targets`);
            check(layout.input === '16px', `${theme}: title inputs do not zoom on focus`);
            await phone.screenshot({ path: path.join(SHOTS, `chapters-phone-${theme}.png`), fullPage: true });
            check(phoneErrors.length === 0, `${theme}: no page errors (${phoneErrors.join('; ')})`);
            await phoneContext.close();
        }
        console.log(`  screenshots in ${SHOTS}`);
    } finally {
        await browser.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

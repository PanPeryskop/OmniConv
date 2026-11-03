const { chromium, devices } = require('playwright');
const { startApp, openEditor, check } = require('./helpers');
const { mockAgent, textProposal, turn, layouts, idle, layoutIssues } = require('./wp6-mock');

const LONG = Array.from({ length: 12 }, (_, i) => `- Item ${i + 1}: the assistant explains a change in a sentence long enough to wrap on a phone.`).join('\n');

async function openFromMenu(page) {
    await page.tap('#peMoreBtn');
    await page.waitForSelector('[data-menu="ext:agent"]');
    await page.tap('[data-menu="ext:agent"]');
    await page.waitForSelector('#peSide:not(.hidden) .pa');
    await page.waitForFunction(() => !document.querySelector('.pa-model .pa-skeleton') && !document.getElementById('peSide').getAnimations().length);
}

(async () => {
    const app = await startApp();
    const browser = await chromium.launch();
    try {
        const { defaultBrowserType, ...phone } = devices['iPhone 13'];
        const context = await browser.newContext(phone);
        const page = await context.newPage();
        const errors = await openEditor(page, app.url, 'pe_test.pdf', { touch: true });
        const blocks = await layouts(page, [0]);
        const [b4, b6, b8] = [4, 6, 8].map(i => blocks[0].blocks[i]);
        const log = await mockAgent(page, {
            turns: [turn(`I found three typos.\n${LONG}`, [
                textProposal('prp_1', 0, b4, 'Pierwszy punkt na liście'),
                textProposal('prp_2', 0, b6, 'Drugi punkt na liście', { depends_on: ['prp_1'] }),
                textProposal('prp_3', 0, b8, 'Trzeci punkt na liście', { depends_on: ['prp_1', 'prp_2'] })
            ])]
        });
        const vw = await page.evaluate(() => window.innerWidth);
        const vh = await page.evaluate(() => window.innerHeight);

        check(!(await page.isVisible('#peAgentBtn')), 'header agent button is hidden on phones');
        await openFromMenu(page);
        check(await page.$eval('#peAgentBtn', el => el.getAttribute('aria-pressed')) === 'true', 'menu entry opens the panel');
        const box = await page.$eval('#peSide', el => el.getBoundingClientRect().toJSON());
        check(box.left === 0 && box.top === 0 && Math.round(box.width) === vw && Math.round(box.height) === vh, 'panel is a full-screen sheet');
        check(await page.isVisible('.pa-grabber'), 'sheet shows a grabber');
        check(!(await page.isVisible('.pa-hint')), 'keyboard hint is hidden on phones');
        check(await page.evaluate(() => document.activeElement?.id === 'paTitle'), 'focus goes to the panel title without raising the keyboard');
        const fonts = await page.$$eval('.pa-input, .pa-scope .cselect-trigger', els => els.map(el => getComputedStyle(el).fontSize));
        check(fonts.every(size => size === '16px'), `inputs use 16 px text (${fonts.join(', ')})`);

        await page.tap('.pa-suggestion[data-key="typos"]');
        await page.waitForSelector('.pa-card[data-id="prp_3"]');
        await idle(page);
        check(log.messages.length === 1, 'suggestion sends a message on phone');
        const small = await page.$$eval('.pa button, .pa textarea, .pa input:not([hidden])', els => els.filter(el => {
            const r = el.getBoundingClientRect();
            return r.width && r.height && (r.height < 44 || r.width < 44);
        }).map(el => `${el.className}:${Math.round(el.getBoundingClientRect().width)}x${Math.round(el.getBoundingClientRect().height)}`));
        check(small.length === 0, `touch targets are at least 44 px (${small.join(', ')})`);
        check((await layoutIssues(page)).length === 0, `no horizontal overflow on phone (${(await layoutIssues(page)).join('; ')})`);

        const scroll = await page.$eval('.pa-log', el => ({ height: el.scrollHeight, client: el.clientHeight, top: el.scrollTop }));
        check(scroll.height > scroll.client && scroll.top + scroll.client >= scroll.height - 2, 'long chat scrolls and sticks to the bottom');
        const editorScroll = await page.$eval('#peScroll', el => el.scrollTop);
        await page.$eval('.pa-log', el => {
            el.scrollTop = 0;
            el.dispatchEvent(new Event('scroll'));
        });
        check(await page.isVisible('.pa-jump'), 'jump button appears after scrolling up');
        check(await page.$eval('#peScroll', el => el.scrollTop) === editorScroll, 'scrolling the chat does not scroll the document');
        check(await page.$eval('.pa-log', el => getComputedStyle(el).overscrollBehaviorY) === 'contain', 'chat scroll is contained');
        await page.tap('.pa-jump');
        check(await page.$eval('.pa-log', el => el.scrollHeight - el.scrollTop - el.clientHeight < 2), 'jump returns to the latest message');

        await page.tap('.pa-input');
        await page.evaluate(() => {
            const root = document.getElementById('pdfEditor');
            root.style.setProperty('--kb', '300px');
            root.classList.add('keyboard');
        });
        const compose = await page.$eval('.pa-compose', el => el.getBoundingClientRect().toJSON());
        check(compose.bottom <= vh - 300 + 1 && compose.bottom >= vh - 300 - 24, `input sits just above the keyboard (bottom ${Math.round(compose.bottom)}, limit ${vh - 300})`);
        const logBox = await page.$eval('.pa-log', el => el.getBoundingClientRect().toJSON());
        check(logBox.height > 100 && logBox.bottom <= compose.top + 1, 'messages stay visible above the input');
        await page.evaluate(() => {
            const root = document.getElementById('pdfEditor');
            root.style.setProperty('--kb', '0px');
            root.classList.remove('keyboard');
        });

        await page.$eval('.pa-card[data-id="prp_1"] [data-pa="show"]', el => el.scrollIntoView({ block: 'center' }));
        await page.tap('.pa-card[data-id="prp_1"] [data-pa="show"]');
        await page.waitForSelector('#peSide.hidden', { state: 'attached' });
        check(await page.$('.pe-focus.proposal') !== null, 'Show closes the sheet and highlights the change');

        await openFromMenu(page);
        await page.$eval('.pa-card[data-id="prp_3"] [data-pa="apply"]', el => el.scrollIntoView({ block: 'center' }));
        await page.tap('.pa-card[data-id="prp_3"] [data-pa="apply"]');
        await page.waitForSelector('.pa-card[data-id="prp_1"].is-applied');
        check((await page.evaluate(() => PdfEditor.bridge.ops())).length === 3, 'apply works on phone with dependencies');

        await page.focus('.pa-input');
        await page.keyboard.press('Escape');
        await page.waitForSelector('#peSide.hidden', { state: 'attached' });
        check(await page.evaluate(() => document.activeElement?.id === 'peMoreBtn'), 'Escape closes the sheet and returns focus to the menu button');

        await openFromMenu(page);
        const grab = await page.$eval('.pa-grabber', el => el.getBoundingClientRect().toJSON());
        await page.mouse.move(grab.x + grab.width / 2, grab.y + 2);
        await page.mouse.down();
        await page.mouse.move(grab.x + grab.width / 2, grab.y + 80, { steps: 4 });
        await page.mouse.move(grab.x + grab.width / 2, grab.y + 160, { steps: 4 });
        await page.mouse.up();
        await page.waitForSelector('#peSide.hidden', { state: 'attached' });
        check(await page.$eval('#peSide', el => el.style.transform === ''), 'dragging the grabber down closes the sheet');
        check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    } finally {
        await browser.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

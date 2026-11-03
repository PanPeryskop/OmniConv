const { chromium, devices } = require('playwright');
const { startApp, openEditor, check } = require('./helpers');
const { SHOTS, mockAgent, textProposal, turn, layouts, idle, layoutIssues, shotPath } = require('./wp6-mock');

const { defaultBrowserType: a, ...IPHONE } = devices['iPhone 13'];
const { defaultBrowserType: b, ...IPAD } = devices['iPad Mini'];
const TARGETS = [
    { name: 'desktop', options: { viewport: { width: 1280, height: 860 } } },
    { name: 'ipad', options: IPAD, touch: true },
    { name: 'iphone', options: IPHONE, touch: true, phone: true }
];

async function open(page, target) {
    if (target.phone) {
        await page.tap('#peMoreBtn');
        await page.tap('[data-menu="ext:agent"]');
    } else if (target.touch) {
        await page.tap('#peAgentBtn');
    } else {
        await page.click('#peAgentBtn');
    }
    await page.waitForSelector('#peSide:not(.hidden) .pa');
    await page.waitForFunction(() => !document.querySelector('.pa-model .pa-skeleton') && !document.getElementById('peSide').getAnimations().length);
}

async function verify(page, target, label) {
    const issues = await layoutIssues(page);
    check(issues.length === 0, `${label}: no horizontal overflow or offscreen elements (${issues.join('; ')})`);
    const fits = await page.evaluate(() => {
        const vh = window.innerHeight;
        return ['.pa-head', '.pa-compose'].every(sel => {
            const r = document.querySelector(sel).getBoundingClientRect();
            return r.top >= 0 && r.bottom <= vh + 1;
        });
    });
    check(fits, `${label}: header and input are on screen`);
    await page.screenshot({ path: shotPath(label) });
}

(async () => {
    const app = await startApp();
    const browser = await chromium.launch();
    try {
        for (const theme of ['dark', 'light']) {
            for (const target of TARGETS) {
                const context = await browser.newContext({ ...target.options, colorScheme: theme });
                await context.addInitScript(value => localStorage.setItem('theme-preference', value), theme);
                const page = await context.newPage();
                const errors = await openEditor(page, app.url, 'pe_test.pdf', { touch: !!target.touch });
                check(await page.evaluate(() => document.documentElement.dataset.theme) === theme, `${theme} theme is active on ${target.name}`);
                const blocks = await layouts(page, [0]);
                const [b4, b6, b8] = [4, 6, 8].map(i => blocks[0].blocks[i]);
                await mockAgent(page, {
                    turns: [turn('I found **three** typos on this page:\n1. `listy` in the first item\n2. the second item\n3. the third item', [
                        textProposal('prp_1', 0, b4, 'Pierwszy punkt na liście', { title: 'Fix typos' }),
                        textProposal('prp_2', 0, b6, 'Drugi punkt na liście', { title: 'Fix typos', depends_on: ['prp_1'] }),
                        textProposal('prp_3', 0, b8, 'Trzeci punkt na liście, który jest bardzo długi i zawiera superdługiesłowobezspacjiktóremusisięzawinąć', { title: 'Fix typos', depends_on: ['prp_1', 'prp_2'] })
                    ])]
                });
                await open(page, target);
                await verify(page, target, `${target.name}-${theme}-empty`);
                const tap = sel => (target.touch ? page.tap(sel) : page.click(sel));
                await tap('.pa-suggestion[data-key="typos"]');
                await page.waitForSelector('.pa-card[data-id="prp_3"]');
                await idle(page);
                await page.$eval('.pa-card[data-id="prp_1"] [data-pa="apply"]', el => el.scrollIntoView({ block: 'center' }));
                await tap('.pa-card[data-id="prp_1"] [data-pa="apply"]');
                await page.waitForSelector('.pa-card[data-id="prp_1"].is-applied');
                await page.waitForTimeout(1800);
                await page.$eval('.pa-log', el => { el.scrollTop = el.scrollHeight; });
                await page.waitForTimeout(150);
                await verify(page, target, `${target.name}-${theme}-chat`);
                check(errors.length === 0, `${target.name}/${theme}: no page errors (${errors.join('; ')})`);
                await context.close();
            }
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

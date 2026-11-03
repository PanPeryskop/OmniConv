const fs = require('fs');
const os = require('os');
const path = require('path');
const { chromium, devices } = require('playwright');
const { startApp, startFakeLm, openEditor, check } = require('./helpers');

const SHOTS = process.env.E2E_SHOTS || path.join(os.tmpdir(), 'device-shots');
const TARGETS = [
    { name: 'iphone-13', options: devices['iPhone 13'], phone: true },
    { name: 'iphone-se', options: devices['iPhone SE'], phone: true },
    { name: 'android-small', options: { ...devices['Galaxy S9+'], viewport: { width: 360, height: 740 } }, phone: true },
    { name: 'iphone-13-landscape', options: devices['iPhone 13 landscape'], phone: true },
    { name: 'ipad-mini', options: devices['iPad Mini'] },
    { name: 'ipad-landscape', options: devices['iPad Pro 11 landscape'] },
    { name: 'desktop', options: { viewport: { width: 1440, height: 900 } } }
];
const RULES = [{
    match: '^Przetłumacz',
    steps: [
        { text: 'Czytam stronę. ', tool_calls: [{ name: 'read_page', args: { page: 3 } }] },
        { tool_calls: [{ name: 'translate', args: { pages: [3], language: 'English' } }] },
        { tool_calls: [{ name: 'finish', args: { summary: 'Gotowe.' } }] }
    ]
}];

function issues(page, selector) {
    return page.evaluate(sel => {
        const found = [];
        const vw = document.documentElement.clientWidth;
        const vh = window.innerHeight;
        if (document.documentElement.scrollWidth > vw + 1) found.push(`document scrolls horizontally ${document.documentElement.scrollWidth} > ${vw}`);
        document.querySelectorAll(sel).forEach(root => {
            const style = getComputedStyle(root);
            if (style.display === 'none' || style.visibility === 'hidden') return;
            const box = root.getBoundingClientRect();
            if (!box.width || !box.height) return;
            if (box.left < -1 || box.right > vw + 1 || box.top < -1 || box.bottom > vh + 1) found.push(`${sel} offscreen ${Math.round(box.left)},${Math.round(box.top)} ${Math.round(box.right)}x${Math.round(box.bottom)}`);
            root.querySelectorAll('button, a, input, select, textarea, [role="button"]').forEach(node => {
                const r = node.getBoundingClientRect();
                const cs = getComputedStyle(node);
                if (!r.width || !r.height || cs.visibility === 'hidden' || node.closest('[hidden], .hidden')) return;
                if (r.width <= 2 && r.height <= 2) return;
                const strip = [...function* up(el) { for (let n = el.parentElement; n && n !== root.parentElement; n = n.parentElement) yield n; }(node)].some(n => ['auto', 'scroll'].includes(getComputedStyle(n).overflowX));
                if (!strip && (r.right > vw + 1 || r.left < -1)) found.push(`${node.tagName}.${node.className} outside x ${Math.round(r.left)}..${Math.round(r.right)}`);
            });
        });
        return found;
    }, selector);
}

function smallTargets(page, selector) {
    return page.evaluate(sel => {
        const found = [];
        document.querySelectorAll(`${sel} button, ${sel} [role="button"], ${sel} input, ${sel} select`).forEach(node => {
            const r = node.getBoundingClientRect();
            const cs = getComputedStyle(node);
            if (!r.width || !r.height || cs.visibility === 'hidden' || cs.pointerEvents === 'none' || node.closest('[hidden], .hidden')) return;
            if (r.width <= 2 && r.height <= 2) return;
            if (Math.min(r.width, r.height) < 32) found.push(`${node.tagName}.${node.className || node.id} ${Math.round(r.width)}x${Math.round(r.height)}`);
        });
        return found;
    }, selector);
}

async function openFromMenu(page, id) {
    await page.click('#peMoreBtn');
    await page.waitForSelector(`[data-menu="ext:${id}"]`);
    await page.click(`[data-menu="ext:${id}"]`);
}

(async () => {
    fs.mkdirSync(SHOTS, { recursive: true });
    const lm = await startFakeLm({ rules: RULES, port: Number(process.env.FAKE_LM_PORT || 5292) });
    const app = await startApp({ port: Number(process.env.E2E_PORT || 5192), env: lm.env });
    const browser = await chromium.launch();
    const problems = [];
    try {
        for (const target of TARGETS) {
            for (const theme of ['dark', 'light']) {
                const label = `${target.name}-${theme}`;
                const context = await browser.newContext({ ...target.options, colorScheme: theme });
                await context.addInitScript(value => localStorage.setItem('theme-preference', value), theme);
                const page = await context.newPage();
                const errors = await openEditor(page, app.url, 'pe_test.pdf', { touch: !!target.options.hasTouch });
                const note = (where, list) => list.forEach(item => problems.push(`${label} ${where}: ${item}`));

                note('editor', await issues(page, '.pe-header, #peDock, .pe-bottom'));
                if (target.phone) note('editor targets', await smallTargets(page, '.pe-header'));
                await page.screenshot({ path: path.join(SHOTS, `${label}-editor.png`) });

                if (target.phone) await openFromMenu(page, 'agent');
                else await page.click('#peAgentBtn');
                await page.waitForSelector('#peSide:not(.hidden) .pa');
                await page.waitForFunction(() => !document.querySelector('.pa-model .pa-skeleton'));
                await page.evaluate(() => {
                    const scope = document.querySelector('#paScope');
                    scope.value = 'document';
                    scope.dispatchEvent(new Event('change', { bubbles: true }));
                });
                await page.fill('.pa-input', 'Przetłumacz stronę 4');
                await page.press('.pa-input', 'Enter');
                await page.waitForSelector('.pa-card', { timeout: 30000 });
                await page.waitForFunction(() => !document.querySelector('.pa.busy'), null, { timeout: 30000 });
                await page.waitForFunction(() => getComputedStyle(document.querySelector('#peSide')).transform === 'none' || !document.getAnimations().length);
                await page.waitForTimeout(400);
                note('agent', await issues(page, '#peSide'));
                if (target.phone) note('agent targets', await smallTargets(page, '#peSide'));
                await page.screenshot({ path: path.join(SHOTS, `${label}-agent.png`) });
                await page.click('.pa-card [data-pa="apply"]');
                await page.waitForSelector('.pa-card.is-applied');
                note('agent applied', await issues(page, '#peSide'));
                await page.click('#peSide [data-pa="close"]');
                await page.waitForSelector('#peSide.hidden', { state: 'attached', timeout: 5000 }).catch(() => note('agent', ['panel did not close']));

                const job = await page.evaluate(() => {
                    const job = PdfProgress.local('translate', { titleKey: 'pe_act_translate', detail: { done: 2, total: 5 }, progress: 0.4 });
                    window.__job = job;
                    return job.task.id;
                });
                check(!!job, `${label}: local task created`);
                if (target.phone) await openFromMenu(page, 'activity');
                else await page.click('#peActivityBtn');
                await page.waitForTimeout(400);
                note('activity', await issues(page, '.pe-activity'));
                await page.screenshot({ path: path.join(SHOTS, `${label}-activity.png`) });
                await page.keyboard.press('Escape');
                await page.evaluate(() => window.__job.done());

                check(errors.length === 0, `${label}: no page errors (${errors.join('; ')})`);
                await context.close();
            }
        }
    } finally {
        await browser.close();
        app.stop();
        lm.stop();
    }
    problems.forEach(item => console.log(`  issue - ${item}`));
    console.log(`  screenshots in ${SHOTS}`);
    check(problems.length === 0, `no layout issues on ${TARGETS.length} devices × 2 themes`);
})().catch(err => {
    console.error(err);
    process.exit(1);
});

const { chromium } = require('playwright');
const { startApp, startFakeLm, openEditor, check } = require('./helpers');

const call = (name, args = {}) => ({ name, args });
const RULES = [
    {
        match: '^Przetłumacz',
        steps: [
            { text: 'Sprawdzam strony. ', tool_calls: [call('list_pages')] },
            { tool_calls: [call('read_page', { page: 3 })] },
            { tool_calls: [call('translate', { pages: [3], language: 'English' })] },
            { tool_calls: [call('finish', { summary: 'Gotowe: przetłumaczyłem stronę 4.' })] }
        ]
    },
    {
        match: 'Zaznacz zdanie',
        steps: [
            { tool_calls: [call('search', { query: 'Highlighted sentence' })] },
            { tool_calls: [call('finish', { summary: 'Nic do zrobienia.' })] }
        ]
    }
];

(async () => {
    const lm = await startFakeLm({ rules: RULES, port: Number(process.env.FAKE_LM_PORT || 5291) });
    const app = await startApp({ port: Number(process.env.E2E_PORT || 5191), env: lm.env });
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const errors = await openEditor(page, app.url);
        await page.waitForSelector('#peAgentBtn:not(.hidden)');
        await page.click('#peAgentBtn');
        await page.waitForSelector('#peSide:not(.hidden) .pa');
        await page.waitForFunction(() => !document.querySelector('.pa-model .pa-skeleton'));
        check(!(await page.$eval('.pa-send', el => el.disabled)), 'send is enabled with the live provider');
        const model = await page.textContent('.pa-model');
        check(/ministral/i.test(model), `status shows the fake model (${model.trim()})`);

        await page.evaluate(() => {
            const scope = document.querySelector('#paScope');
            scope.value = 'document';
            scope.dispatchEvent(new Event('change', { bubbles: true }));
        });
        await page.fill('.pa-input', 'Przetłumacz stronę 4 na angielski');
        await page.press('.pa-input', 'Enter');
        await page.waitForSelector('.pa-card', { timeout: 30000 });
        await page.waitForFunction(() => !document.querySelector('.pa.busy'), null, { timeout: 30000 });
        const chips = await page.$$eval('.pa-tool', els => els.map(el => el.className));
        check(chips.length >= 3, `tool chips are shown (${chips.length})`);
        check(chips.every(name => !/error/.test(name)), 'no tool chip failed');
        const log = await page.textContent('.pa-log');
        check(log.includes('Gotowe: przetłumaczyłem stronę 4.'), 'finish summary is shown');
        const card = await page.textContent('.pa-card');
        check(card.includes('EN:'), 'proposal card shows the translated text');

        const before = await page.evaluate(() => PdfEditor.bridge.ops().length);
        await page.click('.pa-card [data-pa="apply"]');
        await page.waitForSelector('.pa-card.is-applied');
        const ops = await page.evaluate(() => PdfEditor.bridge.ops());
        check(ops.length > before, `applying adds ops (${before} → ${ops.length})`);
        check(ops.every(op => op.page === 3 || ops.indexOf(op) < before), 'applied ops target page 4 only');
        const layer = await page.evaluate(async () => {
            const data = await PdfEditor.bridge.layout(3);
            return (data?.blocks || []).flatMap(b => b.lines.flatMap(l => l.spans.map(sp => sp.t))).join(' ');
        });
        check(layer.includes('EN:'), `the rendered page has the applied translation (${layer.slice(0, 60)})`);

        await page.keyboard.press(process.platform === 'darwin' ? 'Meta+z' : 'Control+z');
        await page.waitForFunction(n => PdfEditor.bridge.ops().length === n, before);
        check(true, 'undo removes the whole proposal group');
        await page.waitForSelector('.pa-card:not(.is-applied)');
        check(true, 'card returns to pending after undo');

        await page.fill('.pa-input', 'Zaznacz zdanie');
        await page.press('.pa-input', 'Enter');
        await page.waitForFunction(() => document.querySelector('.pa-log').textContent.includes('Nic do zrobienia.'), null, { timeout: 30000 });
        await page.waitForFunction(() => !document.querySelector('.pa.busy'));
        check(true, 'second turn in the same session completes');

        const tasks = await page.evaluate(async id => (await fetch(`/api/pdf/edit/tasks?file_id=${id}`).then(r => r.json())).data.tasks, await page.evaluate(() => PdfEditor.bridge.session().fileId));
        check(tasks.some(task => task.kind === 'agent' && task.status === 'done'), 'agent turns are listed as finished tasks');
        check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    } finally {
        await browser.close();
        app.stop();
        lm.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

const { chromium } = require('playwright');
const { startApp, openEditor, check } = require('./helpers');
const { mockAgent, textProposal, turn, layouts, openAgent, sendText, idle, changes } = require('./wp6-mock');

const card = id => `.pa-card[data-id="${id}"]`;
const stateOf = (page, id) => page.$eval(card(id), el => [...el.classList].find(name => name.startsWith('is-')));

(async () => {
    const app = await startApp();
    const browser = await chromium.launch();
    try {
        const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
        const page = await context.newPage();
        const errors = await openEditor(page, app.url);
        const blocks = (await layouts(page, [0, 2]));
        const [b4, b6, b8] = [4, 6, 8].map(i => blocks[0].blocks[i]);
        const typos = [
            textProposal('prp_1', 0, b4, 'Pierwszy punkt na liście', { title: 'Poprawiona literówka' }),
            textProposal('prp_2', 0, b6, 'Drugi punkt na liście', { title: 'Poprawiona literówka 2', depends_on: ['prp_1'] }),
            textProposal('prp_3', 0, b8, 'Trzeci punkt na liście', { title: 'Poprawiona literówka 3', depends_on: ['prp_1', 'prp_2'] })
        ];
        const chain = [
            textProposal('prp_a', 0, b4, 'Punkt A', { title: 'Zmiana A' }),
            textProposal('prp_b', 0, b6, 'Punkt B', { title: 'Zmiana B', depends_on: ['prp_a'] }),
            textProposal('prp_c', 0, b8, 'Punkt C', { title: 'Zmiana C', depends_on: ['prp_a', 'prp_b'] })
        ];
        const log = await mockAgent(page, {
            turns: body => {
                if (/typos|literówki/.test(body.text)) return turn('Znalazłem **3** literówki:\n- pierwsza\n- druga\n- trzecia', typos);
                if (body.text.includes('chain')) return turn('Three dependent changes.', chain, { tools: false });
                if (body.text.includes('stale')) {
                    const ops = PdfEditorOps;
                    return turn('Two pages.', [
                        textProposal('prp_s0', 0, b4, 'Stale candidate', { title: 'Strona 1', base: ops[0] }),
                        textProposal('prp_s2', 2, blocks[2].blocks[0], 'Fresh sentence for markup tests.', { title: 'Strona 3', base: ops[2] })
                    ], { tools: false });
                }
                if (body.text.includes('redact')) {
                    const sensitive = blocks[2].blocks[1];
                    return [
                        ['task', { task_id: 'tsk_r' }],
                        ['delta', { text: 'Checking the document.' }],
                        ['tool', { call_id: 'r1', name: 'redact', args: { patterns: ['pesel', 'iban'] }, status: 'start', summary: '' }],
                        ['tool', { call_id: 'r1', name: 'redact', args: {}, status: 'progress', done: 1, total: 2, summary: '' }],
                        ['proposal', { id: 'prp_r', kind: 'redact', page: 2, title: 'Redact', reason: 'PESEL, IBAN', before: '44051401359, PL61109010140000071219812874', after: '', rects: [sensitive.bbox], ops: [{ type: 'redact', page: 2, rects: [sensitive.bbox] }], base: PdfEditorOps[2], depends_on: [] }],
                        ['tool', { call_id: 'r1', name: 'redact', args: {}, status: 'done', summary: '2 matches' }],
                        ['message', { role: 'assistant', text: 'Redacted 2 values on page 3.' }],
                        ['done', { usage: { steps: 2, tool_calls: 1 }, stopped: false }]
                    ];
                }
                if (body.text.includes('busy')) return { status: 409, error: { code: 'err_agent_failed', message: 'busy' } };
                if (body.text.includes('<b>')) return turn('<img src=x onerror="window.__xss=1"> **ok** `code`', [], { tools: false });
                return null;
            }
        });
        let PdfEditorOps = null;

        await openAgent(page);
        check(await page.$eval('#peAgentBtn', el => el.getAttribute('aria-pressed')) === 'true', 'agent button is pressed when the panel is open');
        check(await page.$eval('#peSide', el => el.getBoundingClientRect().width) === 360, 'panel is a 360 px sidebar on desktop');
        check((await page.textContent('.pa-model')).includes('qwen2.5-7b-instruct'), 'header shows the model');
        check((await page.textContent('.pa-model')).includes('LM Studio'), 'header shows the provider');
        check(await page.$$eval('.pa-suggestion', els => els.length) === 4, 'empty state shows four suggestions');
        check(await page.$('.pa-notice.privacy') === null, 'no privacy note for a local provider');
        check(await page.evaluate(() => document.activeElement?.classList.contains('pa-input')), 'input is focused after opening');
        check(await page.$('.pa-scope .cselect-trigger') !== null, 'scope picker uses CustomSelect');

        await page.click('.pa-suggestion[data-key="typos"]');
        await page.waitForSelector(card('prp_3'));
        await idle(page);
        const first = log.messages[0].body;
        check(first.scope.kind === 'page' && first.scope.pages[0] === 0, 'typo suggestion sends page scope');
        check(Array.isArray(first.ops) && first.selection === null, 'request carries ops and selection');
        check(await page.$$eval('.pa-card.is-pending', els => els.length) === 3, 'three pending proposal cards');
        check(await page.$$eval('.pa-tool.done', els => els.length) === 2, 'tool chips finish in done state');
        check(await page.$eval('.pa-msg.assistant .pa-md', el => el.querySelector('strong')?.textContent === '3' && el.querySelectorAll('li').length === 3), 'assistant text renders markdown-lite');
        check(await page.$eval(card('prp_1'), el => el.querySelector('del')?.textContent.includes('listy') && el.querySelector('ins')?.textContent.includes('na liście')), 'word diff shows removed and added words');
        check(await page.$eval(card('prp_1'), el => !el.querySelector('ins').textContent.includes('Pierwszy')), 'unchanged words are not highlighted');
        check((await page.textContent('.pa-bulk')).includes('3'), 'apply-all bar counts 3 proposals');
        check((await page.textContent(card('prp_3'))).includes('2'), 'dependent card mentions earlier changes');

        await page.hover(card('prp_2'));
        await page.waitForSelector('.pe-focus.proposal');
        check(true, 'hovering a card focuses its rects');
        await page.mouse.move(5, 300);

        await page.click(`${card('prp_1')} [data-pa="apply"]`);
        await page.waitForSelector(`${card('prp_1')}.is-applied`);
        check(await page.$('.pe-focus.applied') !== null, 'applied proposal flashes on the page');
        check(await stateOf(page, 'prp_2') === 'is-pending', 'next chain link stays fresh after its dependency is applied');
        await page.click(`${card('prp_2')} [data-pa="apply"]`);
        await page.waitForSelector(`${card('prp_2')}.is-applied`);
        await page.click(`${card('prp_3')} [data-pa="reject"]`);
        await page.waitForSelector(`${card('prp_3')}.is-rejected`);
        check((await changes(page)).includes('2'), 'change counter shows two changes');
        const ops = await page.evaluate(() => PdfEditor.bridge.ops());
        check(ops.length === 2 && ops[0].g !== ops[1].g, 'each apply is its own undo group');
        check(ops.every(op => op.label && op.proposal), 'applied ops carry label and proposal id');
        check(log.feedback.filter(f => f.decision === 'accepted').length === 2 && log.feedback.some(f => f.proposal_id === 'prp_3' && f.decision === 'rejected'), 'feedback is sent for apply and reject');
        await page.waitForFunction(() => PdfEditor.bridge.layout(0).then(l => l.blocks.some(b => b.lines.some(line => line.spans.some(s => s.t.includes('Drugi punkt na liście'))))));
        check(true, 'applied text shows in the page layout');

        await page.click('.pa-log');
        await page.click('#peUndo');
        await page.waitForSelector(`${card('prp_2')}.is-pending`);
        check((await changes(page)).includes('1'), 'undo removes one group');
        check(await stateOf(page, 'prp_1') === 'is-applied' && await stateOf(page, 'prp_3') === 'is-rejected', 'other cards keep their state after undo');
        await page.click('#peRedo');
        await page.waitForSelector(`${card('prp_2')}.is-applied`);

        await page.click('.pa-head [data-pa="new"]');
        await page.waitForSelector('.pa-empty');
        await page.click('#peUndo');
        await page.click('#peUndo');
        await page.waitForFunction(() => PdfEditor.bridge.ops().length === 0);
        await sendText(page, 'chain please');
        await page.waitForSelector(card('prp_c'));
        await idle(page);
        check(log.messages[1].session !== log.messages[0].session, 'new chat uses a new session');
        await page.click(`${card('prp_c')} [data-pa="apply"]`);
        await page.waitForSelector(`${card('prp_a')}.is-applied`);
        const chained = await page.evaluate(() => PdfEditor.bridge.ops());
        check(chained.length === 3 && new Set(chained.map(op => op.g)).size === 1, 'applying the last link auto-applies its dependencies in one undo group');
        check(chained.map(op => op.proposal).join() === 'prp_a,prp_b,prp_c', 'dependencies are applied in creation order');
        check((await changes(page)).includes('1'), 'change counter counts one change');
        await page.click('#peUndo');
        await page.waitForSelector(`${card('prp_a')}.is-pending`);
        check((await page.textContent('.pa-bulk')).includes('(3)'), 'apply-all shows the pending count');
        await page.click('.pa-bulk [data-pa="apply-all"]');
        await page.waitForSelector(`${card('prp_c')}.is-applied`);
        const all = await page.evaluate(() => PdfEditor.bridge.ops());
        check(all.length === 3 && new Set(all.map(op => op.g)).size === 1 && all[0].label.includes('3'), 'apply all is one labelled undo group');
        check(await page.$('.pa-bulk[hidden]') !== null, 'apply-all bar hides when nothing is pending');
        await page.click('#peUndo');
        await page.waitForSelector(`${card('prp_a')}.is-pending`);
        await page.hover(`${card('prp_a')} [data-pa="reject"]`);
        check(await page.$$eval('.pa-card.doomed', els => els.map(el => el.dataset.id).join()) === 'prp_b,prp_c', 'hovering reject marks dependent cards');
        await page.click(`${card('prp_a')} [data-pa="reject"]`);
        await page.waitForSelector(`${card('prp_c')}.is-rejected`);
        check((await page.textContent(card('prp_b'))).includes('Text fix'), 'cascaded rejection names the rejected proposal');
        check(await page.$eval(`${card('prp_a')} .pa-card-title`, el => el.textContent === 'Text fix' && el.title === 'Zmiana A'), 'card title is localized by kind with the server title as tooltip');
        check(log.feedback.filter(f => f.decision === 'rejected').length === 4, 'cascade sends rejected feedback for dependents');

        await page.click('.pa-head [data-pa="new"]');
        await page.evaluate(() => PdfEditor.bridge.apply([{ type: 'whiteout', page: 2, rect: [400, 700, 450, 720] }], { label: 'manual' }));
        PdfEditorOps = await page.evaluate(() => Object.fromEntries([0, 2].map(id => {
            const ops = PdfEditor.bridge.opsForPage(id);
            return [id, { count: ops.length, last_g: ops.length ? ops[ops.length - 1].g : null }];
        })));
        await sendText(page, 'stale check');
        await page.waitForSelector(card('prp_s2'));
        await idle(page);
        check(await stateOf(page, 'prp_s0') === 'is-pending' && await stateOf(page, 'prp_s2') === 'is-pending', 'proposals with a matching base are fresh');
        await page.evaluate(() => PdfEditor.bridge.apply([{ type: 'whiteout', page: 0, rect: [400, 700, 450, 720] }], { label: 'manual edit' }));
        await page.waitForSelector(`${card('prp_s0')}.is-stale`);
        check(await page.$(`${card('prp_s0')} [data-pa="apply"]`) === null, 'stale proposal cannot be applied');
        check(await stateOf(page, 'prp_s2') === 'is-pending', 'proposal on another page stays fresh');
        check(await page.$('.pa-bulk[hidden]') !== null, 'apply-all bar hides with a single fresh proposal');
        await page.click(`${card('prp_s2')} [data-pa="apply"]`);
        await page.waitForSelector(`${card('prp_s2')}.is-applied`);
        await page.click('#peUndo');
        await page.click('#peUndo');
        await page.waitForSelector(`${card('prp_s0')}.is-pending`);
        check(true, 'undoing the manual edit makes the proposal fresh again');

        await page.click('.pa-scope .cselect-trigger');
        await page.click('.cselect-option[data-value="document"]');
        check((await page.textContent('.pa-scope-note')).includes('5'), 'scope note describes the whole document');
        await sendText(page, 'summary please');
        await idle(page);
        const doc = log.messages[log.messages.length - 1].body;
        check(doc.scope.kind === 'document' && doc.scope.pages.length === 5, 'whole-document scope is sent in the request');
        check(doc.ops.length === 1 && doc.ops[0].type === 'whiteout', 'current ops are sent in the request');

        await page.click('.pa-scope .cselect-trigger');
        await page.click('.cselect-option[data-value="pages"]');
        await page.fill('.pa-pages', '2-3');
        await sendText(page, 'pages please');
        await idle(page);
        const chosen = log.messages[log.messages.length - 1].body;
        check(chosen.scope.kind === 'pages' && chosen.scope.pages.join() === '1,2', 'chosen pages map positions to page ids');

        PdfEditorOps = await page.evaluate(() => Object.fromEntries([0, 2].map(id => {
            const ops = PdfEditor.bridge.opsForPage(id);
            return [id, { count: ops.length, last_g: ops.length ? ops[ops.length - 1].g : null }];
        })));
        await sendText(page, 'redact please');
        await page.waitForSelector(card('prp_r'));
        await idle(page);
        check(await page.$eval(`${card('prp_r')} .pa-card-title`, el => el.textContent) === 'Redaction', 'redact proposal has a localized title');
        check((await page.textContent(`${card('prp_r')} .pa-redacted`)).includes('44051401359'), 'redact card lists the matched values');
        const texts = await page.$$eval('.pa-msg.assistant .pa-md', els => els.slice(-2).map(el => el.textContent));
        check(texts[0] === 'Checking the document.' && texts[1] === 'Redacted 2 values on page 3.', 'finish summary is shown after the streamed text');
        await page.click(`${card('prp_r')} [data-pa="apply"]`);
        await page.waitForSelector(`${card('prp_r')}.is-applied`);
        check((await page.evaluate(() => PdfEditor.bridge.opsForPage(2))).some(op => op.type === 'redact' && op.proposal === 'prp_r'), 'redaction op is applied');
        await page.click('#peUndo');
        await page.waitForSelector(`${card('prp_r')}.is-pending`);

        await sendText(page, 'busy');
        await idle(page);
        check((await page.$$eval('.pa-error', els => els[els.length - 1].textContent)).includes('still working'), 'HTTP 409 shows a friendly busy message');
        check(!(await page.$eval('.pa-input', el => el.disabled)), 'input is enabled again after a turn');

        await sendText(page, 'html <b>');
        await idle(page);
        const lastBubble = await page.$$eval('.pa-msg.assistant .pa-md', els => els[els.length - 1].innerHTML);
        check(!lastBubble.includes('<img') && lastBubble.includes('&lt;img') && lastBubble.includes('<strong>ok</strong>') && lastBubble.includes('<code>code</code>'), 'model HTML is escaped, markdown-lite still renders');
        check(await page.evaluate(() => !window.__xss), 'no script from model text ran');

        const count = await page.$$eval('.pa-log > *', els => els.length);
        const again = await openEditor(page, app.url);
        await openAgent(page);
        check(await page.$$eval('.pa-log > *', els => els.length) === count, 'chat is restored from sessionStorage after reload');
        check(await stateOf(page, 'prp_s2') === 'is-stale', 'restored proposal is stale before the draft ops return');
        await page.click('#peNotice [data-notice="0"]');
        await page.waitForSelector(`${card('prp_s2')}.is-pending`);
        check(true, 'restoring the draft makes the restored proposal fresh again');
        await page.click('.pa-head [data-pa="close"]');
        check(await page.$eval('#peSide', el => el.classList.contains('hidden')), 'close button hides the panel');
        check(await page.$eval('#peAgentBtn', el => el.getAttribute('aria-pressed')) === 'false', 'agent button is not pressed after closing');

        check(errors.length === 0 && again.length === 0, `no page errors (${[...errors, ...again].join('; ')})`);
    } finally {
        await browser.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

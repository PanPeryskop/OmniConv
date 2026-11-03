const { chromium } = require('playwright');
const { startApp, openEditor, check } = require('./helpers');
const { mockAgent, openAgent, sendText, idle } = require('./wp6-mock');

(async () => {
    const app = await startApp();
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const errors = await openEditor(page, app.url);
        await openAgent(page);
        check(await page.$('.pa-notice.off') !== null, 'unfinished backend (501) shows the unavailable state');
        check(await page.$eval('.pa-send', el => el.disabled), 'Send is disabled when the assistant is unavailable');
        await page.click('.pa-head [data-pa="close"]');

        let current = { status: 'llm_offline', provider: 'lmstudio', model: 'qwen2.5-7b-instruct' };
        const log = await mockAgent(page, {
            wrap: false,
            status: () => current,
            turns: [[['task', { task_id: 'tsk_1' }], ['error', { code: 'err_ai_llm_offline', message: 'offline' }]]]
        });
        await openAgent(page);
        const notice = await page.textContent('.pa-notice.off');
        check(notice.includes('LM Studio'), 'offline state shows the localized reason');
        check((await page.textContent('.pa-model')).length > 0 && await page.$('.pa-dot.off') !== null, 'model line shows the offline dot');
        check(await page.$$eval('.pa-suggestion:disabled', els => els.length) === 4, 'suggestions are disabled while offline');
        check(await page.$eval('.pa-send', el => el.disabled), 'Send is disabled while offline');

        current = { status: 'ok', provider: 'lmstudio', model: 'local-test' };
        await page.click('.pa-notice [data-pa="retry"]');
        await page.waitForFunction(() => !document.querySelector('.pa-notice.off'));
        check((await page.textContent('.pa-model')).includes('LM Studio · local-test'), 'model line shows the local provider after retry');
        check(await page.$('.pa-notice') === null, 'no notice while the local model is ready');
        check(!(await page.$eval('.pa-send', el => el.disabled)), 'Send is enabled again after retry');

        await sendText(page, 'hello');
        await idle(page);
        check(await page.$('.pa-error') !== null, 'error event is shown in the log');
        check(await page.$('.pa-notice.off') !== null, 'LLM offline error flips the panel to offline');

        await page.evaluate(() => i18n.setLanguage('pl'));
        await page.waitForFunction(() => document.querySelector('.pa-title')?.textContent === 'Asystent AI');
        check((await page.textContent('.pa-notice.off')).includes('LM Studio nie jest uruchomione'), 'reason is translated to Polish');
        check((await page.$eval('.pa-input', el => el.placeholder)).includes('asystenta'), 'input placeholder is translated');
        await page.evaluate(() => i18n.setLanguage('de'));
        await page.waitForFunction(() => document.querySelector('.pa-input')?.placeholder.includes('Assistenten'));
        check(true, 'German translations are registered');
        await page.evaluate(() => i18n.setLanguage('en'));
        check(log.status >= 2, 'status is fetched on open and on retry');
        check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    } finally {
        await browser.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

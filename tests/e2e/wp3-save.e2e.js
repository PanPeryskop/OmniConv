const { chromium } = require('playwright');
const { startApp, openEditor, check } = require('./helpers');

(async () => {
    const app = await startApp();
    const browser = await chromium.launch();
    try {
        const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
        const errors = await openEditor(page, app.url);
        await page.evaluate(() => PdfEditor.bridge.apply([
            { type: 'whiteout', page: 0, rect: [60, 400, 200, 440] },
            { type: 'whiteout', page: 3, rect: [60, 400, 200, 440] }
        ], { label: 'wp3' }));
        const [response] = await Promise.all([
            page.waitForResponse(res => res.url().endsWith('/api/pdf/process')),
            page.click('#peSave')
        ]);
        const jobId = (await response.json()).data.job_id;
        const status = await page.evaluate(async jobId => {
            const seen = [];
            for (let i = 0; i < 100; i++) {
                const res = await fetch(`/api/status/${jobId}`).then(r => r.json());
                const job = res.data || res;
                seen.push(job.progress);
                if (['completed', 'failed', 'cancelled'].includes(job.status)) return { status: job.status, seen };
                await new Promise(resolve => setTimeout(resolve, 100));
            }
            return { status: 'timeout', seen };
        }, jobId);
        check(status.status === 'completed', `save job completes (${status.status})`);
        check(status.seen[status.seen.length - 1] === 100, 'save job reaches 100 %');
        check(errors.length === 0, `no page errors (${errors.join('; ')})`);
    } finally {
        await browser.close();
        app.stop();
    }
})().catch(err => {
    console.error(err);
    process.exit(1);
});

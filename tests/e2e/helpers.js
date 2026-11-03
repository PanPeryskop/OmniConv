const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROOT = path.resolve(__dirname, '../..');
const PYTHON = process.env.E2E_PYTHON || (process.platform === 'win32' ? path.join(ROOT, '.venv', 'Scripts', 'python.exe') : path.join(ROOT, '.venv', 'bin', 'python'));
const FIXTURES = path.join(ROOT, 'tests', 'fixtures');

async function waitFor(url, timeout = 30000) {
    const until = Date.now() + timeout;
    while (Date.now() < until) {
        try {
            const res = await fetch(url);
            if (res.ok) return;
        } catch (err) {
            await new Promise(r => setTimeout(r, 250));
        }
    }
    throw new Error(`Timed out waiting for ${url}`);
}

function launch(args, env) {
    const child = spawn(PYTHON, args, { cwd: ROOT, env: { ...process.env, ...env }, stdio: ['ignore', 'ignore', 'pipe'] });
    let errors = '';
    child.stderr.on('data', chunk => { errors = (errors + chunk).slice(-4000); });
    child.logs = () => errors;
    return child;
}

async function startApp({ port = Number(process.env.E2E_PORT || 5099), env = {} } = {}) {
    const child = launch([path.join('tests', 'e2e', 'serve.py'), String(port)], env);
    const url = `http://127.0.0.1:${port}`;
    await waitFor(`${url}/pdf`);
    return { url, child, stop: () => child.kill() };
}

async function startFakeLm({ rules = [], port = Number(process.env.FAKE_LM_PORT || 1234) } = {}) {
    const file = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'fake-lm-')), 'rules.json');
    fs.writeFileSync(file, JSON.stringify(rules));
    const child = launch([path.join('tests', 'fakes', 'fake_lm.py'), String(port)], { FAKE_LM_RULES: file });
    await waitFor(`http://127.0.0.1:${port}/api/v1/models`);
    const env = { LMSTUDIO_API_URL: `http://127.0.0.1:${port}/api/v1/chat` };
    return { child, port, env, rulesFile: file, setRules: next => fs.writeFileSync(file, JSON.stringify(next)), stop: () => child.kill() };
}

async function openEditor(page, url, fixture = 'pe_test.pdf', { touch = false } = {}) {
    const errors = [];
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(`${url}/pdf`);
    await page.setInputFiles('#pdfInput', path.join(FIXTURES, fixture));
    const card = '.tool-card[data-tool="edit"]';
    await page.waitForSelector(card);
    if (touch) await page.tap(card);
    else await page.click(card);
    await page.waitForSelector('#pdfEditor:not(.hidden) .pe-page');
    await page.waitForFunction(() => typeof PdfEditor !== 'undefined' && PdfEditor.bridge.session()?.digest);
    return errors;
}

function check(condition, message) {
    if (!condition) throw new Error(`Assertion failed: ${message}`);
    console.log(`  ok - ${message}`);
}

module.exports = { ROOT, FIXTURES, startApp, startFakeLm, openEditor, check, waitFor };

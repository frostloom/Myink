import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

test('cleans its profile and signal handlers after a browser launch failure', { timeout: 10000 }, async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'myink-launch-failure-check-'))
  const child = spawn(process.execPath, ['--input-type=module', '-e', `
    import assert from 'node:assert/strict';
    const signals = ['SIGTERM', 'SIGINT'];
    const before = signals.map(signal => process.listenerCount(signal));
    const { launchBrowser } = await import(${JSON.stringify(new URL('./browser-options.mjs', import.meta.url).href)});
    await assert.rejects(launchBrowser(), /executable.*doesn't exist/i);
    assert.deepEqual(signals.map(signal => process.listenerCount(signal)), before);
  `], { env: { ...process.env, TMPDIR: root, MYINK_TEST_BROWSER: 'chromium', P1_CHROMIUM_EXECUTABLE: path.join(root, 'missing-browser') }, stdio: ['ignore', 'ignore', 'pipe'] })
  const closed = once(child, 'close')
  let stderr = ''
  child.stderr.on('data', bytes => { stderr += bytes })
  try {
    const [code] = await closed
    assert.equal(code, 0, stderr)
    assert.deepEqual(fs.readdirSync(root).filter(name => name.startsWith('myink-browser-profile-')), [])
  } finally {
    if (child.exitCode === null && child.signalCode === null) { child.kill('SIGKILL'); await closed }
    fs.rmSync(root, { recursive: true, force: true })
  }
})

for (const signal of ['SIGTERM', 'SIGINT']) {
  test(`cleans its own browser profile when interrupted with ${signal}`, { timeout: 45000 }, async () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'myink-interrupt-check-'))
    const child = spawn(process.execPath, ['--input-type=module', '-e', `
      const { launchBrowser } = await import(${JSON.stringify(new URL('./browser-options.mjs', import.meta.url).href)});
      await launchBrowser();
      console.log('ready');
      setInterval(() => {}, 1000);
    `], { env: { ...process.env, TMPDIR: root, MYINK_TEST_BROWSER: 'chromium' }, stdio: ['ignore', 'pipe', 'pipe'] })
    const closed = once(child, 'close')
    let stderr = ''
    child.stderr.on('data', bytes => { stderr += bytes })
    const deadline = setTimeout(() => child.kill('SIGKILL'), 35000)
    try {
      await Promise.race([
        new Promise(resolve => child.stdout.on('data', bytes => { if (bytes.toString().includes('ready')) resolve() })),
        closed.then(() => { throw new Error(`Browser failed before ready: ${stderr}`) }),
      ])
      assert.ok(fs.readdirSync(root).some(name => name.startsWith('myink-browser-profile-')))
      child.kill(signal)
      const [code, exitSignal] = await closed
      assert.ok(code !== 0 || exitSignal, 'An interrupted run cannot report success')
      assert.deepEqual(fs.readdirSync(root).filter(name => name.startsWith('myink-browser-profile-')), [])
    } finally {
      clearTimeout(deadline)
      if (child.exitCode === null && child.signalCode === null) { child.kill('SIGKILL'); await closed }
      fs.rmSync(root, { recursive: true, force: true })
    }
  })
}

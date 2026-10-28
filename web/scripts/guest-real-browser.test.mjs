import { test } from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

test('missing navigation produces a failed receipt and closes browser/proxy', { timeout: 45000 }, async () => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'myink-guest-failure-probe-'))
  const metadata = path.join(output, 'metadata.json')
  fs.writeFileSync(metadata, JSON.stringify({ ip: '2001:db8::1', users: [] }))
  const child = spawn(process.execPath, [fileURLToPath(new URL('./guest-real-browser.mjs', import.meta.url)), '--output', output], {
    env: { ...process.env, MYINK_GUEST_METADATA: metadata, MYINK_GUEST_REAL_API: 'http://127.0.0.1:1', MYINK_GUEST_FAILURE_PROBE: 'missing-navigation' },
    stdio: ['ignore', 'ignore', 'pipe'],
  })
  let stderr = ''
  child.stderr.on('data', bytes => { stderr += bytes })
  const closed = new Promise(resolve => child.once('close', (code, signal) => resolve({ code, signal })))
  const deadline = setTimeout(() => child.kill('SIGTERM'), 30000)
  const hardDeadline = setTimeout(() => child.kill('SIGKILL'), 35000)
  try {
    const result = await closed
    assert.equal(result.code, 1, stderr)
    const receipt = JSON.parse(fs.readFileSync(path.join(output, 'receipt.json'), 'utf8'))
    assert.equal(receipt.passed, false)
    assert.match(receipt.error, /Timeout.*100ms/i)
    assert.equal(receipt.browserClosed, true)
    assert.equal(receipt.proxyClosed, true)
    assert.deepEqual(receipt.cleanupErrors, [])
  } finally {
    clearTimeout(deadline)
    clearTimeout(hardDeadline)
    if (child.exitCode === null && child.signalCode === null) { child.kill('SIGKILL'); await closed }
    fs.rmSync(output, { recursive: true, force: true })
  }
})

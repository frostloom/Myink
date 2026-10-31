import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { finalizeBrowserReceipt } from './browser-receipt.mjs'
import * as browserReceipt from './browser-receipt.mjs'

test('cleanup failure cannot publish success or prevent remaining cleanup', async () => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'myink-receipt-test-'))
  let serverClosed = false
  try {
    await finalizeBrowserReceipt({ passed: true }, output, [
      async () => { throw new Error('browser close failed') },
      async () => { serverClosed = true },
    ])
    assert.equal(serverClosed, true)
    const receipt = JSON.parse(fs.readFileSync(path.join(output, 'receipt.json')))
    assert.equal(receipt.passed, false)
    assert.deepEqual(receipt.cleanupErrors, ['Error: browser close failed'])
  } finally { fs.rmSync(output, { recursive: true, force: true }) }
})

test('successful cleanup preserves a prior scenario failure', async () => {
  const output = fs.mkdtempSync(path.join(os.tmpdir(), 'myink-receipt-test-'))
  try {
    await finalizeBrowserReceipt({ passed: false, error: 'scenario failed' }, output, [async () => {}])
    const receipt = JSON.parse(fs.readFileSync(path.join(output, 'receipt.json')))
    assert.equal(receipt.passed, false)
    assert.equal(receipt.error, 'scenario failed')
    assert.deepEqual(receipt.cleanupErrors, [])
  } finally { fs.rmSync(output, { recursive: true, force: true }) }
})


test('failure annotations expose stage and stack without extra workflow commands', () => {
  const line = browserReceipt.browserFailureAnnotation('firefox', 'readiness', 'Expected 100%\r\n::warning title=injected::text')
  assert.equal(line, '::error title=firefox/readiness::Expected 100%25%0D%0A::warning title=injected::text')
  assert.equal(line.split('\n').length, 1)
})

test('failure annotation properties cannot add workflow attributes', () => {
  const line = browserReceipt.browserFailureAnnotation('webkit', 'stage,extra:value', 'assertion failed')
  assert.equal(line, '::error title=webkit/stage%2Cextra%3Avalue::assertion failed')
})

test('oversized failure annotations are bounded and explicitly truncated', () => {
  const line = browserReceipt.browserFailureAnnotation('chromium', 'guest', 'x'.repeat(5000))
  assert.ok(line.length < 4300)
  assert.ok(line.endsWith('[truncated]'))
  assert.ok(line.includes('x'.repeat(4096)))
})

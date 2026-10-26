import { createHash } from 'node:crypto'
// Validate a built, isolated Caddy image without contacting any application API.
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { chromium } from 'playwright'
const value = name => { const index = process.argv.indexOf(name); assert.ok(index >= 0, `${name} required`); return process.argv[index + 1] }
const image = value('--image'), expected = value('--expected')
assert.ok(['react', 'vue'].includes(expected))
const docker = process.env.MYINK_DOCKER ?? 'docker'
const run = args => execFileSync(docker, args, { encoding: 'utf8', timeout: 60000 }).trim()
const output = fs.mkdtempSync(path.join(os.tmpdir(), 'myink-image-smoke-'))
const receipt = { kind: 'isolated_frontend_image_smoke', image, expected, checks: [], pageErrors: [], passed: false }
let browser, container, network
try {
  const metadata = JSON.parse(run(['image', 'inspect', image]))[0]
  receipt.imageId = metadata.Id
  receipt.revision = metadata.Config.Labels?.['org.opencontainers.image.revision']
  assert.equal(metadata.Config.Labels?.['io.myink.frontend'], expected, 'Image must identify the selected frontend')
  receipt.checks.push('selected_frontend_label')
  const suffix = `${Date.now()}-${process.pid}`
  network = `myink-image-smoke-${suffix}`
  run(['network', 'create', network])
  container = `myink-image-smoke-${suffix}`
  run(['run', '-d', '--init', '--name', container, '--network', network, '-e', 'SITE_ADDRESS=http://:80', '-p', '127.0.0.1::80', image])
  const origin = `http://${run(['port', container, '80/tcp']).split('\n')[0]}`
  let ready = false
  for (let i = 0; i < 60; i++) {
    try { if ((await fetch(origin + '/login')).ok) { ready = true; break } } catch { /* startup */ }
    await new Promise(resolve => setTimeout(resolve, 250))
  }
  assert.ok(ready, 'Isolated Caddy failed to serve the frontend')
  const html = await fetch(origin + '/login')
  assert.match(html.headers.get('cache-control'), /no-store/)
  const source = await html.text()
  const entry = source.match(/src="(\/assets\/index-[^"]+\.js)"/)?.[1]
  assert.ok(entry, 'Hashed module entry is required')
  const asset = await fetch(origin + entry)
  assert.equal(asset.status, 200); assert.match(asset.headers.get('cache-control'), /immutable/)
  receipt.entry = entry
  receipt.entrySha256 = createHash('sha256').update(Buffer.from(await asset.arrayBuffer())).digest('hex')
  receipt.checks.push('deep_link_html_no_store', 'hashed_asset_immutable')
  receipt.retainedAssets = {}
  for (let previous = 0; previous < process.argv.length; previous++) {
    if (process.argv[previous] !== '--required-asset') continue
    const required = process.argv[previous + 1]
    assert.match(required, /^\/assets\/[^/]+\.(?:js|css)$/)
    const retained = await fetch(origin + required)
    assert.equal(retained.status, 200, 'Previously served hashed assets must survive the switch')
    receipt.retainedAssets[required] = createHash('sha256').update(Buffer.from(await retained.arrayBuffer())).digest('hex')
    receipt.checks.push('previous_asset_retained')
  }

  const unknown = await fetch(origin + '/api/not-a-version')
  assert.equal(unknown.status, 404); assert.match(unknown.headers.get('content-type'), /json/)
  receipt.checks.push('unknown_api_never_spa')
  browser = await chromium.launch({ headless: true, ...(process.env.P1_CHROMIUM_EXECUTABLE ? { executablePath: process.env.P1_CHROMIUM_EXECUTABLE } : {}) })
  const page = await browser.newPage()
  page.on('pageerror', error => receipt.pageErrors.push(error.message))
  await page.route('**/*', route => new URL(route.request().url()).origin === origin ? route.continue() : route.abort())
  await page.goto(origin + '/login'); await page.getByLabel('用户名', { exact: true }).waitFor()
  const releaseResponse = await fetch(origin + '/release.json')
  assert.equal(releaseResponse.status, 200); assert.match(releaseResponse.headers.get('cache-control'), /no-store/)
  assert.match(releaseResponse.headers.get('content-type'), /json/)
  const release = await releaseResponse.json()
  assert.equal(release.client, expected); assert.equal(release.entry, entry); assert.match(release.id, new RegExp(`^${expected}-[a-f0-9]{64}$`))
  assert.deepEqual(JSON.parse(await page.locator('meta[name="myink-release"]').getAttribute('content')), release)
  receipt.release = release; receipt.checks.push('release_manifest_html_binding_no_store')
  assert.equal(await page.evaluate(() => Boolean(document.querySelector('#root')?.__vue_app__)), expected === 'vue')
  await page.reload(); await page.getByLabel('用户名', { exact: true }).waitFor()
  assert.deepEqual(receipt.pageErrors, [])
  receipt.checks.push('selected_native_runtime', 'login_deep_link_refresh')
  await page.screenshot({ path: path.join(output, 'login.png'), fullPage: true })
  receipt.passed = true
} catch (error) { receipt.error = String(error); throw error }
finally {
  // Run every cleanup even if a preceding one fails, and never report success
  // when the test infrastructure could not be cleaned up.
  receipt.cleanupErrors = []
  try { await browser?.close() } catch (error) { receipt.cleanupErrors.push(`browser: ${error}`) }
  if (container) { try { run(['rm', '-f', '-v', container]) } catch (error) { receipt.cleanupErrors.push(`container: ${error}`) } }
  if (network) { try { run(['network', 'rm', network]) } catch (error) { receipt.cleanupErrors.push(`network: ${error}`) } }
  if (receipt.cleanupErrors.length) { receipt.passed = false; process.exitCode = 1 }
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2))
  console.log(JSON.stringify({ output, ...receipt }, null, 2))
}

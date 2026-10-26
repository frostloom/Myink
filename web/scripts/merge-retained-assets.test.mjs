import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, symlinkSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { spawnSync } from 'node:child_process'
const script = new URL('./merge-retained-assets.mjs', import.meta.url)
function setup(t) {
  const root = mkdtempSync(join(tmpdir(), 'myink-asset-merge-'))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const source = join(root, 'old'), target = join(root, 'new')
  mkdirSync(source); mkdirSync(target)
  return { source, target, run: () => spawnSync(process.execPath, [script.pathname, source, target], { encoding: 'utf8' }) }
}
test('merges prior assets and preserves matching current bytes', t => {
  const f = setup(t)
  writeFileSync(join(f.source, 'old.js'), 'old'); writeFileSync(join(f.source, 'same.js'), 'same')
  writeFileSync(join(f.target, 'same.js'), 'same'); writeFileSync(join(f.target, 'new.js'), 'new')
  assert.equal(f.run().status, 0)
  assert.equal(readFileSync(join(f.target, 'old.js'), 'utf8'), 'old')
  assert.equal(readFileSync(join(f.target, 'new.js'), 'utf8'), 'new')
})
test('rejects collision without replacing current code', t => {
  const f = setup(t)
  writeFileSync(join(f.source, 'index.js'), 'old'); writeFileSync(join(f.target, 'index.js'), 'current')
  const result = f.run()
  assert.notEqual(result.status, 0); assert.match(result.stderr, /Asset content differs/)
  assert.equal(readFileSync(join(f.target, 'index.js'), 'utf8'), 'current')
})
test('rejects symlinks instead of following public assets outside the capture', t => {
  const f = setup(t)
  symlinkSync('/etc/hosts', join(f.source, 'external.js'))
  const result = f.run()
  assert.notEqual(result.status, 0); assert.match(result.stderr, /symlink/)
})

import { chromium, firefox, webkit } from 'playwright'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

export const browserName = process.env.MYINK_TEST_BROWSER ?? 'chromium'
const engines = { chromium, firefox, webkit }
if (!Object.hasOwn(engines, browserName)) throw new Error(`Unsupported test browser: ${browserName}`)

export async function launchBrowser() {
  // WebKit ephemeral contexts cannot persist any Blob in IndexedDB. Use a fresh
  // normal profile for every engine; never access the user's browser profile.
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'myink-browser-profile-'))
  let context, launching, closing
  const signals = new Map([['SIGTERM', 143], ['SIGINT', 130]])
  const handlers = new Map()
  function close() {
    if (closing) return closing
    closing = (async () => {
      try {
        // A signal can arrive while the browser is still starting.
        await launching?.catch(() => {})
        await context?.close()
      } finally {
        for (const [signal, handler] of handlers) process.off(signal, handler)
        fs.rmSync(profile, { recursive: true, force: true })
      }
    })()
    return closing
  }
  for (const [signal, code] of signals) {
    const handler = () => { void close().then(() => process.exit(code), () => process.exit(1)) }
    handlers.set(signal, handler)
    process.on(signal, handler)
  }
  try {
    launching = engines[browserName].launchPersistentContext(profile, {
      headless: true, acceptDownloads: true,
      handleSIGTERM: false, handleSIGINT: false,
      ...(browserName === 'chromium' && process.env.P1_CHROMIUM_EXECUTABLE ? { executablePath: process.env.P1_CHROMIUM_EXECUTABLE } : {}),
    })
    context = await launching
  } catch (error) {
    await close()
    throw error
  }
  return {
    version: () => context.browser().version(),
    async newPage(options = {}) {
      const page = await context.newPage()
      if (options.viewport) await page.setViewportSize(options.viewport)
      return page
    },
    close,
  }
}

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
  let context
  try {
    context = await engines[browserName].launchPersistentContext(profile, {
      headless: true, acceptDownloads: true,
      ...(browserName === 'chromium' && process.env.P1_CHROMIUM_EXECUTABLE ? { executablePath: process.env.P1_CHROMIUM_EXECUTABLE } : {}),
    })
  } catch (error) {
    fs.rmSync(profile, { recursive: true, force: true })
    throw error
  }
  return {
    version: () => context.browser().version(),
    async newPage(options = {}) {
      const page = await context.newPage()
      if (options.viewport) await page.setViewportSize(options.viewport)
      return page
    },
    async close() {
      try { await context.close() } finally { fs.rmSync(profile, { recursive: true, force: true }) }
    },
  }
}

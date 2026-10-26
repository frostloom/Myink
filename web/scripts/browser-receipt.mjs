import fs from 'node:fs'
import path from 'node:path'

export async function finalizeBrowserReceipt(receipt, output, cleanups) {
  receipt.cleanupErrors = []
  for (const cleanup of cleanups) {
    try { await cleanup() }
    catch (error) { receipt.cleanupErrors.push(String(error)) }
  }
  if (receipt.cleanupErrors.length) receipt.passed = false
  fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2))
}

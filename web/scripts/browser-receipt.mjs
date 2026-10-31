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

// A single bounded Actions annotation remains visible through check-run APIs,
// even when downloading the full job log/artifact requires authentication.
export function browserFailureAnnotation(browser, stage, reason) {
  const escape = value => String(value).replaceAll('%', '%25').replaceAll('\r', '%0D').replaceAll('\n', '%0A')
  const text = String(reason ?? 'Stage failed without diagnostics')
  const message = text.length > 4096 ? text.slice(0, 4096) + ' [truncated]' : text
  const title = escape(`${browser}/${stage}`).replaceAll(':', '%3A').replaceAll(',', '%2C')
  return `::error title=${title}::${escape(message)}`
}

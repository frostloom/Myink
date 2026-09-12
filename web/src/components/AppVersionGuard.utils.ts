const ENTRY_BUNDLE_PATTERN = /<script\b[^>]*\bsrc=["']([^"']*\/assets\/index-[^"']+\.js)["'][^>]*>/i

export function bundlePathFromIndex(html: string): string | null {
  return html.match(ENTRY_BUNDLE_PATTERN)?.[1] ?? null
}

export function isDifferentBundle(current: string | null, latest: string | null): boolean {
  return Boolean(current && latest && current !== latest)
}

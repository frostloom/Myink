// Merge public prior hashes without allowing them to replace current code.
import { readdirSync, lstatSync, existsSync, readFileSync, mkdirSync, copyFileSync } from 'node:fs'
import { resolve, join, dirname } from 'node:path'
const [sourceArgument, targetArgument] = process.argv.slice(2)
if (!sourceArgument || !targetArgument) throw new Error('source and target directories required')
const source = resolve(sourceArgument), target = resolve(targetArgument)
const pending = []
function inspect(directory, relative = '') {
  for (const name of readdirSync(directory)) {
    const path = join(directory, name), entry = join(relative, name), destination = join(target, entry)
    const stat = lstatSync(path)
    if (stat.isSymbolicLink()) throw new Error(`Asset symlink rejected: ${entry}`)
    if (stat.isDirectory()) { inspect(path, entry); continue }
    if (!stat.isFile()) throw new Error(`Unsupported asset: ${entry}`)
    if (name === '.gitkeep') continue
    if (existsSync(destination)) {
      if (!lstatSync(destination).isFile() || !readFileSync(path).equals(readFileSync(destination))) {
        throw new Error(`Asset content differs: ${entry}`)
      }
    } else pending.push([path, destination])
  }
}
// Validate all entries before changing the target.
inspect(source)
for (const [path, destination] of pending) {
  mkdirSync(dirname(destination), { recursive: true })
  copyFileSync(path, destination)
}

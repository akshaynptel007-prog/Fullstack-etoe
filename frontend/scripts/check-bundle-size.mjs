#!/usr/bin/env node
// Performance budget gate (CI). The case study asks for "bundle < 200 KB";
// we enforce the strict reading — all JS+CSS *minified, uncompressed* — plus
// a gzip budget for what the sale page needs before it is interactive.
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { gzipSync } from 'node:zlib'

const DIST = new URL('../dist/', import.meta.url).pathname
const TOTAL_RAW_BUDGET = 200 * 1024 // everything the app can ever load, minified
const INITIAL_GZIP_BUDGET = 75 * 1024 // bytes on the wire before the sale page is interactive

const walk = (dir) =>
  readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })

let files
try {
  files = walk(DIST).filter((f) => /\.(js|css)$/.test(f))
} catch {
  console.error('dist/ not found — run `npm run build` first')
  process.exit(1)
}

// Initial = files referenced directly by index.html (entry + modulepreloads + CSS).
const html = readFileSync(join(DIST, 'index.html'), 'utf8')
const initialNames = new Set([...html.matchAll(/(?:src|href)="\/(assets\/[^"]+)"/g)].map((m) => m[1]))

const rows = files.map((file) => {
  const raw = readFileSync(file)
  const name = relative(DIST, file)
  return { name, raw: raw.length, gzip: gzipSync(raw, { level: 9 }).length, initial: initialNames.has(name) }
})
const kb = (n) => `${(n / 1024).toFixed(1)} KB`
const totalRaw = rows.reduce((s, r) => s + r.raw, 0)
const totalGzip = rows.reduce((s, r) => s + r.gzip, 0)
const initialGzip = rows.filter((r) => r.initial).reduce((s, r) => s + r.gzip, 0)

console.log('\nBundle (minified → gzip)')
for (const r of rows.sort((a, b) => b.gzip - a.gzip)) {
  console.log(`  ${r.initial ? '●' : '○'} ${r.name.padEnd(42)} ${kb(r.raw).padStart(10)} → ${kb(r.gzip).padStart(9)}`)
}
console.log(`\n  total minified : ${kb(totalRaw).padStart(9)}  (budget ${kb(TOTAL_RAW_BUDGET)})`)
console.log(`  total gzip     : ${kb(totalGzip).padStart(9)}`)
console.log(`  ● initial gzip : ${kb(initialGzip).padStart(9)}  (budget ${kb(INITIAL_GZIP_BUDGET)})\n`)

if (totalRaw > TOTAL_RAW_BUDGET || initialGzip > INITIAL_GZIP_BUDGET) {
  console.error('✗ Bundle budget exceeded')
  process.exit(1)
}
console.log('✓ Within budget')

/** PLAN M3RC: syntax-aware product-voice scan; comments and identities are not labels. */
import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from '../web/node_modules/typescript/lib/typescript.js'

export function violations(text, filename) {
  const source = ts.createSourceFile(filename, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const failures = []
  const banned = /\b(?:ensem[bl]le|garden|relay)\b/iu
  const workId = /\b(?:M[123][A-Z0-9]+|SYM\d+)\b/u
  function visit(node) {
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node) || ts.isJsxText(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node)) {
      const value = node.text
      // SPEC B.6 fixture-isolation identities are mandatory, never ordinary owner copy.
      const fixture = /^(?:M2C|M2G|M2ST4|M3FP|SYM13) REGRESSION$/u.test(value)
      if (!fixture && (banned.test(value) || workId.test(value))) {
        const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1
        failures.push(`${filename}:${line}: internal vocabulary in product copy: ${value.trim()}`)
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  return failures
}

export function scan(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const path = resolve(directory, entry.name)
    return entry.isDirectory() ? scan(path)
      : /\.(?:ts|tsx)$/u.test(path) ? violations(readFileSync(path, 'utf8'), path) : []
  })
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = resolve(process.argv[2] ?? fileURLToPath(new URL('../web/src', import.meta.url)))
  const failures = scan(root)
  failures.forEach(line => console.error(line))
  console.log(`Product voice: ${failures.length ? 'FAIL' : 'PASS'}`)
  process.exitCode = failures.length ? 1 : 0
}

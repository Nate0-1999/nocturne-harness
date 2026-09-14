/** SPEC B.6 r14: parse core TypeScript throws and disabled interaction gates. */
import { readFileSync, readdirSync } from 'node:fs'
import { resolve } from 'node:path'
import ts from '../web/node_modules/typescript/lib/typescript.js'

const root = resolve(process.argv[2] ?? new URL('..', import.meta.url).pathname)
const citation = /\b(?:(?:WALL|INCIDENT)\s+\S+|F\d{3}\b|A-\d{3}\b|D\.2\s+\d+\b)/u
const tests = readdirSync(resolve(root, 'web/tests')).filter(p => p.endsWith('.mjs'))
  .map(p => readFileSync(resolve(root, 'web/tests', p), 'utf8')).join('\n')
let failures = 0
for (const file of ['store.ts', 'socket.ts', 'App.tsx', 'rackBridge.tsx']) {
  const text = readFileSync(resolve(root, 'web/src', file), 'utf8')
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  const lines = text.split('\n')
  function visit(node) {
    // PLAN M3GD limits App.tsx to the conversation/composer, not settings or curation.
    if (file === 'App.tsx' && ts.isFunctionDeclaration(node) && node.name?.text !== 'ChatModule') return
    const refusal = ts.isThrowStatement(node)
    const gate = ts.isJsxAttribute(node) && node.name.getText(source) === 'disabled'
      && node.initializer?.getText(source) !== '{false}'
    if (refusal || gate) {
      const line = source.getLineAndCharacterOfPosition(node.getStart(source)).line
      let nearby = lines.slice(Math.max(0, line - 1), line + 1).join('\n')
      if (refusal && ts.isBlock(node.parent) && ts.isIfStatement(node.parent.parent)) {
        const branch = source.getLineAndCharacterOfPosition(node.parent.parent.getStart(source)).line
        nearby += lines.slice(Math.max(0, branch - 1), branch + 1).join('\n')
      }
      if (!citation.test(nearby)) {
        console.error(`web/src/${file}:${line + 1}: ${refusal ? 'throw' : 'disabled gate'} lacks adjacent WALL/incident citation`)
        failures++
      }
      if (refusal && ts.isNewExpression(node.expression)) {
        for (const arg of node.expression.arguments ?? []) {
          if (ts.isStringLiteral(arg) && !tests.includes(arg.text)) {
            console.error(`web/src/${file}:${line + 1}: error message unquoted by web tests: ${arg.text}`)
            failures++
          }
        }
      }
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
}
process.exitCode = failures ? 1 : 0

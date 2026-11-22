import type { Nodes } from 'mdast'
import { unified } from 'unified'
import remarkParse from 'remark-parse'
import remarkGfm from 'remark-gfm'

const markdown = unified().use(remarkParse).use(remarkGfm)
const segmenter = typeof Intl.Segmenter === 'function'
  ? new Intl.Segmenter(undefined, { granularity: 'sentence' }) : null

function spoken(node: Nodes): string {
  switch (node.type) {
    case 'code': return '\nCode block skipped.\n'
    case 'table': return '\nTable skipped.\n'
    case 'text':
    case 'inlineCode': return node.value
    case 'image':
    case 'imageReference': return node.alt ?? ''
    case 'break': return ' '
    case 'html':
    case 'definition':
    case 'footnoteDefinition': return ''
    default:
      return 'children' in node ? node.children.map(spoken).join(
        ['root', 'list', 'listItem', 'blockquote'].includes(node.type) ? '\n' : '',
      ) : ''
  }
}

/** The rendered Markdown and the reader use the same GFM grammar. */
export function speechSentences(source: string, finished: boolean): string[] {
  const blocks = markdown.parse(source).children
  return blocks.flatMap((block, index) => {
    const text = spoken(block).trim()
    const segments = segmenter ? Array.from(segmenter.segment(text), part => part.segment)
      : text.split(/(?<=[.!?。！？])\s+/u)
    const sentences = segments.map(part => part.trim()).filter(Boolean)
    if (finished || index < blocks.length - 1 || block.type === 'code' || block.type === 'table') return sentences
    // An unfinished pipe row can still become the header of a GFM table.
    if (block.type === 'paragraph' && source.slice(block.position?.start.offset).split('\n')[0].includes('|')) return []
    // The last segment can still grow, including after a token ending in a period.
    return sentences.slice(0, -1)
  })
}

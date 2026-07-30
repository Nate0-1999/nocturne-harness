import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

const ASSISTANT_MARKDOWN_ELEMENTS = [
  'p',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'strong',
  'em',
  'ul',
  'ol',
  'li',
  'table',
  'thead',
  'tbody',
  'tr',
  'th',
  'td',
  'pre',
  'code',
  'br',
] as const

interface AssistantMarkdownProps {
  content: string
}

export function AssistantMarkdown({ content }: AssistantMarkdownProps) {
  return (
    <div
      className="message__content message__content--markdown"
      data-testid="assistant-markdown"
    >
      <ReactMarkdown
        allowedElements={ASSISTANT_MARKDOWN_ELEMENTS}
        remarkPlugins={[remarkGfm]}
        skipHtml={false}
        unwrapDisallowed
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

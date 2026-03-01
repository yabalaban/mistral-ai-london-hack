import { useMemo } from 'preact/hooks'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

// Configure marked for inline-friendly output
marked.setOptions({
  breaks: true,
  gfm: true,
})

interface MarkdownProps {
  content: string
  class?: string
}

export function Markdown({ content, class: className }: MarkdownProps) {
  const html = useMemo(() => {
    // Parse markdown to HTML, then sanitize to prevent XSS
    const raw = marked.parse(content, { async: false }) as string
    return DOMPurify.sanitize(raw)
  }, [content])

  return (
    <div
      class={`markdown-content ${className ?? ''}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

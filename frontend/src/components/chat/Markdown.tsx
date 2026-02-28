import { useMemo } from 'preact/hooks'
import { marked } from 'marked'

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
    // Parse markdown to HTML
    const raw = marked.parse(content, { async: false }) as string
    return raw
  }, [content])

  return (
    <div
      class={`markdown-content ${className ?? ''}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

import { Markdown } from './Markdown.tsx'

interface StreamingTextProps {
  text: string
}

export function StreamingText({ text }: StreamingTextProps) {
  return (
    <span>
      <Markdown content={text} />
      <span class="inline-block w-2 h-4 bg-accent/60 rounded-sm animate-pulse ml-0.5 align-text-bottom" />
    </span>
  )
}

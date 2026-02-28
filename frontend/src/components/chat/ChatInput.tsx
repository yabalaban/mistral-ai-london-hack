import { useState } from 'preact/hooks'
import { ImageUpload } from '../shared/ImageUpload.tsx'
import type { Attachment } from '../../types/index.ts'

interface ChatInputProps {
  onSend: (content: string, attachments?: Attachment[]) => void
  disabled?: boolean
  placeholder?: string
}

export function ChatInput({
  onSend,
  disabled = false,
  placeholder = 'Type a message...',
}: ChatInputProps) {
  const [text, setText] = useState('')
  const [attachments, setAttachments] = useState<Attachment[]>([])

  const handleSubmit = () => {
    const trimmed = text.trim()
    if (!trimmed && attachments.length === 0) return
    onSend(trimmed, attachments.length > 0 ? attachments : undefined)
    setText('')
    setAttachments([])
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  const handleImageUpload = (dataUrl: string, fileName: string) => {
    setAttachments((prev) => [...prev, { type: 'image', url: dataUrl, name: fileName }])
  }

  const removeAttachment = (index: number) => {
    setAttachments((prev) => prev.filter((_, i) => i !== index))
  }

  return (
    <div class="px-4 pb-4">
      {attachments.length > 0 && (
        <div class="flex gap-2 mb-2 p-2 glass rounded-xl">
          {attachments.map((att, i) => (
            <div key={i} class="relative group">
              <img src={att.url} alt={att.name} class="h-16 rounded" />
              <button
                onClick={() => removeAttachment(i)}
                class="absolute -top-1 -right-1 bg-danger text-white rounded-full w-4 h-4 text-xs leading-none flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
              >
                &times;
              </button>
            </div>
          ))}
        </div>
      )}
      <div class="flex items-end gap-2 glass rounded-2xl px-3 py-2">
        <ImageUpload onUpload={handleImageUpload} />
        <textarea
          value={text}
          onInput={(e) => setText((e.target as HTMLTextAreaElement).value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          rows={1}
          class="flex-1 bg-transparent text-zinc-900 placeholder-zinc-400 outline-none resize-none text-sm max-h-32"
          style={{ minHeight: '24px' }}
        />
        <button
          onClick={handleSubmit}
          disabled={disabled || (!text.trim() && attachments.length === 0)}
          class="p-1.5 text-accent hover:text-accent-hover disabled:text-zinc-300 transition-colors"
        >
          <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
            <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z" />
          </svg>
        </button>
      </div>
    </div>
  )
}

import { useRef } from 'preact/hooks'

interface ImageUploadProps {
  onUpload: (dataUrl: string, fileName: string) => void
}

export function ImageUpload({ onUpload }: ImageUploadProps) {
  const inputRef = useRef<HTMLInputElement>(null)

  const handleChange = (e: Event) => {
    const file = (e.target as HTMLInputElement).files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onloadend = () => {
      onUpload(reader.result as string, file.name)
    }
    reader.readAsDataURL(file)

    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        class="hidden"
        onChange={handleChange}
      />
      <button
        onClick={() => inputRef.current?.click()}
        class="p-2 text-white/40 hover:text-white transition-colors"
        title="Upload image"
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"
          />
        </svg>
      </button>
    </>
  )
}

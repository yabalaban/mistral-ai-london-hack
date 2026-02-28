import { useState } from 'preact/hooks'

interface AvatarProps {
  src?: string
  name: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  speaking?: boolean
}

const sizes = {
  sm: 'w-8 h-8 text-xs',
  md: 'w-10 h-10 text-sm',
  lg: 'w-14 h-14 text-base',
  xl: 'w-20 h-20 text-2xl',
}

const colors = [
  'bg-indigo-500',
  'bg-emerald-500',
  'bg-amber-500',
  'bg-rose-500',
  'bg-purple-500',
  'bg-teal-500',
]

function getColor(name: string) {
  let hash = 0
  for (const ch of name) hash = (hash + ch.charCodeAt(0)) % colors.length
  return colors[hash]
}

export function Avatar({ src, name, size = 'md', speaking = false }: AvatarProps) {
  const [imgError, setImgError] = useState(false)
  const sizeClass = sizes[size]
  const ringClass = speaking ? 'ring-2 ring-accent speaking-ring' : ''
  const showImg = src && !imgError

  return (
    <div
      class={`${sizeClass} ${ringClass} rounded-full flex-shrink-0 overflow-hidden flex items-center justify-center`}
    >
      {showImg ? (
        <img src={src} alt={name} class="w-full h-full object-cover" onError={() => setImgError(true)} />
      ) : (
        <div
          class={`w-full h-full flex items-center justify-center ${getColor(name)} text-white font-semibold`}
        >
          {name[0]?.toUpperCase()}
        </div>
      )}
    </div>
  )
}

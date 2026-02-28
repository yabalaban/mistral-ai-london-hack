interface AvatarProps {
  src?: string
  name: string
  size?: 'sm' | 'md' | 'lg' | 'xl'
  speaking?: boolean
}

const sizes = {
  sm: 'w-8 h-8 text-xs',
  md: 'w-10 h-10 text-sm',
  lg: 'w-12 h-12 text-base',
  xl: 'w-20 h-20 text-2xl',
}

const colors = [
  'bg-dc-blurple',
  'bg-dc-green',
  'bg-amber-600',
  'bg-rose-600',
  'bg-purple-600',
  'bg-teal-600',
]

function getColor(name: string) {
  let hash = 0
  for (const ch of name) hash = (hash + ch.charCodeAt(0)) % colors.length
  return colors[hash]
}

export function Avatar({ src, name, size = 'md', speaking = false }: AvatarProps) {
  const sizeClass = sizes[size]
  const ringClass = speaking ? 'ring-2 ring-dc-green animate-pulse' : ''

  return (
    <div
      class={`${sizeClass} ${ringClass} rounded-full flex-shrink-0 overflow-hidden flex items-center justify-center`}
    >
      {src ? (
        <img src={src} alt={name} class="w-full h-full object-cover" />
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

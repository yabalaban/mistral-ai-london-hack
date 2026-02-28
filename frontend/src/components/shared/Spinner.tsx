export function Spinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const dims = { sm: 'w-1.5 h-1.5', md: 'w-2 h-2', lg: 'w-3 h-3' }
  const gap = { sm: 'gap-1', md: 'gap-1.5', lg: 'gap-2' }
  return (
    <div class={`flex items-center ${gap[size]}`}>
      <div class={`${dims[size]} rounded-full bg-accent dot-pulse-1`} />
      <div class={`${dims[size]} rounded-full bg-accent dot-pulse-2`} />
      <div class={`${dims[size]} rounded-full bg-accent dot-pulse-3`} />
    </div>
  )
}

export function Spinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const dims = { sm: 'w-4 h-4', md: 'w-8 h-8', lg: 'w-12 h-12' }
  return (
    <div class={`${dims[size]} animate-spin rounded-full border-2 border-dc-text-muted border-t-dc-blurple`} />
  )
}

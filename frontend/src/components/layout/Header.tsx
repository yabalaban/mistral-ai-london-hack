import type { ComponentChildren } from 'preact'

interface HeaderProps {
  title: string
  children?: ComponentChildren
}

export function Header({ title, children }: HeaderProps) {
  return (
    <div class="h-14 min-h-14 flex items-center px-4 border-b border-zinc-200 glass-subtle">
      <h2 class="font-semibold text-zinc-900" style="font-family: 'Sora', sans-serif">{title}</h2>
      <div class="ml-auto flex items-center gap-2">
        {children}
      </div>
    </div>
  )
}

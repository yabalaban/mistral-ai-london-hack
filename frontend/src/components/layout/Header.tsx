import type { ComponentChildren } from 'preact'

interface HeaderProps {
  title: string
  children?: ComponentChildren
}

export function Header({ title, children }: HeaderProps) {
  return (
    <div class="h-12 min-h-12 flex items-center px-4 border-b border-dc-primary shadow-sm bg-dc-tertiary">
      <h2 class="font-semibold text-dc-text">{title}</h2>
      <div class="ml-auto flex items-center gap-2">{children}</div>
    </div>
  )
}

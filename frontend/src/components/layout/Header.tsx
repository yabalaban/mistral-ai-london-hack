import type { ComponentChildren } from 'preact'
import { mobileSidebarOpen } from '../../state/ui.ts'

interface HeaderProps {
  title: string
  children?: ComponentChildren
}

export function Header({ title, children }: HeaderProps) {
  return (
    <div class="h-14 min-h-14 flex items-center px-4 border-b border-zinc-200 glass-subtle">
      <button
        class="md:hidden p-1.5 -ml-1 mr-2 text-zinc-500 hover:text-zinc-900 transition-colors"
        onClick={() => { mobileSidebarOpen.value = !mobileSidebarOpen.value }}
      >
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      <h2 class="font-semibold text-zinc-900 truncate" style="font-family: 'Sora', sans-serif">{title}</h2>
      <div class="ml-auto flex items-center gap-2 flex-shrink-0">
        {children}
      </div>
    </div>
  )
}

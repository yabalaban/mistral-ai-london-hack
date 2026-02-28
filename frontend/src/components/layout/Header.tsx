import type { ComponentChildren } from 'preact'

interface HeaderProps {
  title: string
  children?: ComponentChildren
  onToggleLogs?: () => void
}

export function Header({ title, children, onToggleLogs }: HeaderProps) {
  return (
    <div class="h-14 min-h-14 flex items-center px-4 border-b border-white/5 glass-subtle">
      <h2 class="font-semibold text-white">{title}</h2>
      <div class="ml-auto flex items-center gap-2">
        {children}
        {onToggleLogs && (
          <button
            onClick={onToggleLogs}
            class="p-2 text-white/40 hover:text-white transition-colors"
            title="Toggle logs"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
          </button>
        )}
      </div>
    </div>
  )
}

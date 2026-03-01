import type { ComponentChildren } from 'preact'
import { useEffect } from 'preact/hooks'
import { Sidebar } from './Sidebar.tsx'
import { useAgents } from '../../hooks/useAgents.ts'
import { errorMessage } from '../../state/ui.ts'

interface ShellProps {
  children: ComponentChildren
}

export function Shell({ children }: ShellProps) {
  useAgents()

  const error = errorMessage.value

  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => {
        errorMessage.value = null
      }, 5000)
      return () => clearTimeout(timer)
    }
  }, [error])

  return (
    <div class="flex flex-col md:flex-row h-screen w-screen overflow-hidden">
      <Sidebar />
      <main class="flex-1 flex flex-col min-w-0 min-h-0">{children}</main>

      {error && (
        <div class="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-3 px-4 py-3 rounded-lg bg-red-600 text-white shadow-lg max-w-lg w-[calc(100%-2rem)]">
          <span class="flex-1 text-sm">{error}</span>
          <button
            type="button"
            class="shrink-0 p-1 rounded hover:bg-red-500 transition-colors"
            onClick={() => { errorMessage.value = null }}
            aria-label="Dismiss error"
          >
            <svg class="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
              <path
                fill-rule="evenodd"
                d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z"
                clip-rule="evenodd"
              />
            </svg>
          </button>
        </div>
      )}
    </div>
  )
}

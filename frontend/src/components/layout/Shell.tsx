import type { ComponentChildren } from 'preact'
import { Sidebar } from './Sidebar.tsx'
import { useAgents } from '../../hooks/useAgents.ts'

interface ShellProps {
  children: ComponentChildren
}

export function Shell({ children }: ShellProps) {
  useAgents()

  return (
    <div class="flex h-screen w-screen overflow-hidden">
      <Sidebar />
      <main class="flex-1 flex flex-col min-w-0">{children}</main>
    </div>
  )
}

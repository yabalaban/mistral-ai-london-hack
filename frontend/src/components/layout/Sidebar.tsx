import { mobileSidebarOpen } from '../../state/ui.ts'

export function Sidebar() {
  const isOpen = mobileSidebarOpen.value

  const closeSidebar = () => {
    mobileSidebarOpen.value = false
  }

  return (
    <>
      {/* Mobile overlay backdrop */}
      {isOpen && (
        <div
          class="fixed inset-0 bg-black/40 z-40 md:hidden"
          onClick={closeSidebar}
        />
      )}
      <div class={`
        w-60 min-w-60 glass-strong border-r border-zinc-200 flex flex-col h-full
        fixed inset-y-0 left-0 z-50 transition-transform duration-200
        ${isOpen ? 'translate-x-0' : '-translate-x-full'}
        md:static md:translate-x-0
      `}>
        <div class="h-14 min-h-14 flex items-center px-4 border-b border-zinc-200">
          <div class="flex items-center gap-2">
            <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
              <circle cx="10" cy="14" r="8" stroke="#6366F1" stroke-width="2" fill="none" opacity="0.8" />
              <circle cx="18" cy="14" r="8" stroke="#6366F1" stroke-width="2" fill="none" opacity="0.5" />
            </svg>
            <h1 class="font-bold text-zinc-900 tracking-wide" style="font-family: 'Sora', sans-serif">Circles</h1>
          </div>
        </div>

        <nav class="flex-1 p-3 flex flex-col gap-1">
          <a
            href="/"
            onClick={closeSidebar}
            class="flex items-center gap-3 px-3 py-2 rounded-xl text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <span class="text-sm font-medium">Agents</span>
          </a>
          <a
            href="/activity"
            onClick={closeSidebar}
            class="flex items-center gap-3 px-3 py-2 rounded-xl text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900 transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <span class="text-sm font-medium">Activity Feed</span>
          </a>
        </nav>

        <div class="p-3 border-t border-zinc-200">
          <div class="text-[10px] text-zinc-400 text-center">Observability Dashboard</div>
        </div>
      </div>
    </>
  )
}

import { signal } from '@preact/signals'

export const mobileSidebarOpen = signal(false)

/** Latest WS or API error message shown to the user. Set to null to dismiss. */
export const errorMessage = signal<string | null>(null)

import { Header } from '../layout/Header.tsx'
import { ActivityFeed } from './ActivityFeed.tsx'
import { ConversationFilter } from './ConversationFilter.tsx'
import { useActivityFeed } from '../../hooks/useActivityFeed.ts'
import { allEvents } from '../../state/activity.ts'

interface ActivityPageProps {
  path?: string
}

export function ActivityPage(_props: ActivityPageProps) {
  useActivityFeed()

  return (
    <>
      <Header title="Activity Feed">
        <span class="text-xs text-zinc-400">{allEvents.value.length} events</span>
      </Header>
      <div class="flex-1 flex min-h-0">
        {/* Filter sidebar */}
        <div class="w-48 min-w-48 border-r border-zinc-200 p-3 overflow-y-auto hidden md:block">
          <ConversationFilter />
        </div>
        {/* Feed */}
        <div class="flex-1 flex flex-col min-h-0">
          <ActivityFeed />
        </div>
      </div>
    </>
  )
}

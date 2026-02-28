import Router from 'preact-router'
import { Shell } from './components/layout/Shell.tsx'
import { RosterPage } from './components/roster/RosterPage.tsx'
import { ChatPage } from './components/chat/ChatPage.tsx'
import { GroupPage } from './components/group/GroupPage.tsx'

export function App() {
  return (
    <Shell>
      <Router>
        <RosterPage path="/" />
        <ChatPage path="/chat/:id" />
        <GroupPage path="/group/:id" />
      </Router>
    </Shell>
  )
}

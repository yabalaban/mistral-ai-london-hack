import Router from 'preact-router'
import { Shell } from './components/layout/Shell.tsx'
import { RosterPage } from './components/roster/RosterPage.tsx'
import { ActivityPage } from './components/activity/ActivityPage.tsx'

export function App() {
  return (
    <Shell>
      <Router>
        <RosterPage path="/" />
        <ActivityPage path="/activity" />
      </Router>
    </Shell>
  )
}

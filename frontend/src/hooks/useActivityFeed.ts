import { useEffect } from 'preact/hooks'
import { connectEventsFeed, disconnectEventsFeed } from '../api/eventsWs.ts'

export function useActivityFeed() {
  useEffect(() => {
    connectEventsFeed()
    return () => disconnectEventsFeed()
  }, [])
}

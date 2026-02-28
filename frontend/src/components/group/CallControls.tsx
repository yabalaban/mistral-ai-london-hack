import { callMode, isMicOn } from '../../state/call.ts'

interface CallControlsProps {
  onToggleMic: () => void
  onEndCall: () => void
  onToggleMode: () => void
}

export function CallControls({ onToggleMic, onEndCall, onToggleMode }: CallControlsProps) {
  const mode = callMode.value
  const micOn = isMicOn.value

  return (
    <div class="flex items-center justify-center gap-4 py-4 bg-dc-secondary border-t border-dc-primary">
      {/* Mode toggle */}
      <button
        onClick={onToggleMode}
        class="flex items-center gap-2 px-4 py-2 rounded-full bg-dc-tertiary hover:bg-dc-input text-dc-text-secondary hover:text-dc-text transition-colors text-sm"
      >
        {mode === 'voice' ? (
          <>
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            Text Mode
          </>
        ) : (
          <>
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
            Voice Mode
          </>
        )}
      </button>

      {/* Mic toggle (voice mode only) */}
      {mode === 'voice' && (
        <button
          onClick={onToggleMic}
          class={`p-3 rounded-full transition-colors ${
            micOn
              ? 'bg-dc-green text-white'
              : 'bg-dc-tertiary text-dc-text-muted hover:text-dc-text'
          }`}
        >
          <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            {micOn ? (
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            ) : (
              <>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4" />
                <line x1="3" y1="3" x2="21" y2="21" stroke="currentColor" stroke-width="2" stroke-linecap="round" />
              </>
            )}
          </svg>
        </button>
      )}

      {/* End call */}
      <button
        onClick={onEndCall}
        class="px-6 py-2 bg-dc-red hover:bg-red-600 text-white rounded-full font-medium text-sm transition-colors"
      >
        End Call
      </button>
    </div>
  )
}

import { callMode, isPTTActive } from '../../state/call.ts'

interface CallControlsProps {
  onStartPTT: () => void
  onStopPTT: () => void
  onEndCall: () => void
  onToggleMode: () => void
}

export function CallControls({ onStartPTT, onStopPTT, onEndCall, onToggleMode }: CallControlsProps) {
  const mode = callMode.value
  const pttActive = isPTTActive.value

  return (
    <div class="border-t border-zinc-200">
      {/* Main button row */}
      <div class="flex items-center justify-center gap-4 py-4 glass-subtle">
        {/* Mode toggle */}
        <button
          onClick={onToggleMode}
          class="flex items-center gap-2 px-4 py-2 rounded-full glass hover:bg-zinc-50 text-zinc-600 hover:text-zinc-900 transition-colors text-sm"
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

        {/* PTT button (voice mode only) */}
        {mode === 'voice' && (
          <button
            onPointerDown={onStartPTT}
            onPointerUp={onStopPTT}
            onPointerLeave={onStopPTT}
            onPointerCancel={onStopPTT}
            class={`p-3 rounded-full transition-all select-none touch-none ${
              pttActive
                ? 'bg-accent text-white glow-accent scale-110'
                : 'glass text-zinc-500 hover:text-zinc-700 hover:bg-zinc-50'
            }`}
          >
            <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
            </svg>
          </button>
        )}

        {/* End call */}
        <button
          onClick={onEndCall}
          class="px-6 py-2 bg-danger hover:bg-red-600 text-white rounded-full font-medium text-sm transition-colors"
        >
          End Call
        </button>
      </div>

      {/* Hold to talk hint */}
      {mode === 'voice' && !pttActive && (
        <div class="text-center pb-2 text-[11px] text-zinc-300">
          Hold Space or mic button to talk
        </div>
      )}
    </div>
  )
}

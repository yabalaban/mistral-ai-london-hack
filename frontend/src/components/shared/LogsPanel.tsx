import { useState } from 'preact/hooks'

export interface LogEntry {
  id: string
  type: 'WS' | 'API' | 'INFO'
  label: string
  detail?: string
  timestamp: string
  metadata?: Record<string, string>
}

interface LogsPanelProps {
  open: boolean
  onClose: () => void
  entries: LogEntry[]
}

const typeBadge: Record<LogEntry['type'], string> = {
  WS: 'bg-accent/20 text-accent border border-accent/20',
  API: 'bg-amber-500/20 text-amber-400 border border-amber-500/20',
  INFO: 'bg-white/10 text-white/60 border border-white/10',
}

export function LogsPanel({ open, onClose, entries }: LogsPanelProps) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const toggle = (id: string) => {
    const next = new Set(expanded)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setExpanded(next)
  }

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          class="fixed inset-0 bg-black/30 z-40 transition-opacity"
          onClick={onClose}
        />
      )}

      {/* Panel */}
      <div
        class={`fixed top-0 right-0 h-full w-96 z-50 glass-strong border-l border-white/10 flex flex-col transition-transform duration-300 ${
          open ? 'translate-x-0' : 'translate-x-full'
        }`}
      >
        <div class="flex items-center justify-between px-4 py-3 border-b border-white/10">
          <h3 class="font-semibold text-white">Logs</h3>
          <button
            onClick={onClose}
            class="text-white/40 hover:text-white transition-colors"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div class="flex-1 overflow-y-auto p-3 space-y-2">
          {entries.length === 0 && (
            <div class="text-white/40 text-sm text-center py-8">No log entries yet</div>
          )}
          {entries.map((entry) => (
            <div
              key={entry.id}
              class="glass rounded-xl p-3 cursor-pointer hover:bg-white/[.08] transition-colors"
              onClick={() => entry.detail && toggle(entry.id)}
            >
              <div class="flex items-start gap-2">
                <span class={`text-[10px] font-bold px-1.5 py-0.5 rounded ${typeBadge[entry.type]}`}>
                  {entry.type}
                </span>
                <div class="flex-1 min-w-0">
                  <div class="text-sm text-white/90 truncate">{entry.label}</div>
                  <div class="text-[10px] text-white/40 mt-0.5">{entry.timestamp}</div>
                </div>
              </div>

              {expanded.has(entry.id) && entry.detail && (
                <pre class="mt-2 text-xs text-white/60 font-mono bg-black/20 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                  {entry.detail}
                </pre>
              )}

              {entry.metadata && (
                <div class="flex flex-wrap gap-1 mt-2">
                  {Object.entries(entry.metadata).map(([k, v]) => (
                    <span
                      key={k}
                      class="text-[10px] px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-white/40"
                    >
                      {k}: {v}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </>
  )
}

import { useState } from 'preact/hooks'
import { Button } from '../shared/Button.tsx'
import { Avatar } from '../shared/Avatar.tsx'
import type { Agent } from '../../types/index.ts'

interface CreateAgentModalProps {
  onClose: () => void
  onCreate: (agent: Agent) => void
}

interface AgentTemplate {
  name: string
  role: string
  bio: string
  personality: string
  tools: string[]
}

const templates: AgentTemplate[] = [
  {
    name: 'Research Assistant',
    role: 'Researcher',
    bio: 'Thorough researcher who digs deep into topics, synthesizes information from multiple sources, and presents clear findings.',
    personality: 'Curious, methodical, thorough',
    tools: ['web_search', 'analysis'],
  },
  {
    name: 'Code Reviewer',
    role: 'Software Engineer',
    bio: 'Experienced engineer focused on code quality, security, and best practices. Reviews PRs with precision.',
    personality: 'Detail-oriented, constructive, pragmatic',
    tools: ['code_interpreter'],
  },
  {
    name: 'Creative Writer',
    role: 'Content Creator',
    bio: 'Versatile writer who crafts compelling copy, stories, and marketing content with a keen eye for tone and audience.',
    personality: 'Creative, articulate, adaptable',
    tools: ['web_search'],
  },
  {
    name: 'Data Analyst',
    role: 'Analytics Expert',
    bio: 'Turns raw data into actionable insights. Expert in visualization, statistical analysis, and spotting trends.',
    personality: 'Analytical, precise, data-driven',
    tools: ['code_interpreter', 'analysis'],
  },
]

export function CreateAgentModal({ onClose, onCreate }: CreateAgentModalProps) {
  const [step, setStep] = useState<'template' | 'customize'>('template')
  const [selected, setSelected] = useState<AgentTemplate | null>(null)
  const [name, setName] = useState('')
  const [role, setRole] = useState('')
  const [bio, setBio] = useState('')
  const [personality, setPersonality] = useState('')

  const selectTemplate = (t: AgentTemplate) => {
    setSelected(t)
    setName(t.name)
    setRole(t.role)
    setBio(t.bio)
    setPersonality(t.personality)
    setStep('customize')
  }

  const handleCreate = () => {
    if (!name.trim()) return
    onCreate({
      id: `agent-${Date.now()}`,
      name: name.trim(),
      role: role.trim(),
      bio: bio.trim(),
      avatar: '',
      personality: personality.trim(),
      tools: selected?.tools ?? [],
    })
  }

  return (
    <div
      class="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div class="glass-strong rounded-2xl glow-soft max-w-lg w-full mx-4 overflow-hidden">
        <div class="px-6 py-4 border-b border-white/10 flex items-center justify-between">
          <h3 class="text-lg font-semibold text-white">
            {step === 'template' ? 'Create Agent' : 'Customize Agent'}
          </h3>
          <button onClick={onClose} class="text-white/40 hover:text-white transition-colors">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {step === 'template' ? (
          <div class="p-4 space-y-2 max-h-96 overflow-y-auto">
            {templates.map((t) => (
              <button
                key={t.name}
                onClick={() => selectTemplate(t)}
                class="w-full text-left glass rounded-xl p-4 hover:bg-white/10 transition-colors"
              >
                <div class="flex items-start gap-3">
                  <Avatar name={t.name} size="md" />
                  <div class="min-w-0 flex-1">
                    <div class="font-medium text-white">{t.name}</div>
                    <div class="text-sm text-accent">{t.role}</div>
                    <p class="text-xs text-white/50 mt-1 line-clamp-2">{t.bio}</p>
                    <div class="flex gap-1 mt-2">
                      {t.tools.map((tool) => (
                        <span key={tool} class="text-[10px] px-1.5 py-0.5 rounded bg-white/5 border border-white/10 text-white/40">
                          {tool}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              </button>
            ))}
            <button
              onClick={() => {
                setSelected(null)
                setStep('customize')
              }}
              class="w-full text-left glass rounded-xl p-4 hover:bg-white/10 transition-colors border border-dashed border-white/20"
            >
              <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-full bg-white/5 flex items-center justify-center text-white/40">
                  <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4" />
                  </svg>
                </div>
                <div>
                  <div class="font-medium text-white/70">Blank Agent</div>
                  <div class="text-xs text-white/40">Start from scratch</div>
                </div>
              </div>
            </button>
          </div>
        ) : (
          <div class="p-6 space-y-4">
            <div>
              <label class="text-xs font-medium text-white/40 uppercase tracking-wider">Name</label>
              <input
                value={name}
                onInput={(e) => setName((e.target as HTMLInputElement).value)}
                class="w-full mt-1 px-3 py-2 bg-white/5 border border-white/10 rounded-xl text-white text-sm outline-none focus:border-accent/50 transition-colors"
                placeholder="Agent name"
              />
            </div>
            <div>
              <label class="text-xs font-medium text-white/40 uppercase tracking-wider">Role</label>
              <input
                value={role}
                onInput={(e) => setRole((e.target as HTMLInputElement).value)}
                class="w-full mt-1 px-3 py-2 bg-white/5 border border-white/10 rounded-xl text-white text-sm outline-none focus:border-accent/50 transition-colors"
                placeholder="e.g. Software Engineer"
              />
            </div>
            <div>
              <label class="text-xs font-medium text-white/40 uppercase tracking-wider">Bio</label>
              <textarea
                value={bio}
                onInput={(e) => setBio((e.target as HTMLTextAreaElement).value)}
                rows={2}
                class="w-full mt-1 px-3 py-2 bg-white/5 border border-white/10 rounded-xl text-white text-sm outline-none focus:border-accent/50 transition-colors resize-none"
                placeholder="Short description..."
              />
            </div>
            <div>
              <label class="text-xs font-medium text-white/40 uppercase tracking-wider">Personality</label>
              <input
                value={personality}
                onInput={(e) => setPersonality((e.target as HTMLInputElement).value)}
                class="w-full mt-1 px-3 py-2 bg-white/5 border border-white/10 rounded-xl text-white text-sm outline-none focus:border-accent/50 transition-colors"
                placeholder="e.g. Curious, methodical"
              />
            </div>
            <div class="flex gap-2 pt-2">
              <Button variant="secondary" onClick={() => setStep('template')} class="flex-1">
                Back
              </Button>
              <Button onClick={handleCreate} disabled={!name.trim()} class="flex-1">
                Create Agent
              </Button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

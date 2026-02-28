import { signal } from '@preact/signals'
import type { GroupCall } from '../types/index.ts'

export const activeCall = signal<GroupCall | null>(null)
export const currentSpeaker = signal<string | null>(null)
export const callMode = signal<'text' | 'voice'>('text')
export const partialTranscript = signal<string | null>(null)
export const agentSpeaking = signal<string | null>(null)
export const isPTTActive = signal(false)

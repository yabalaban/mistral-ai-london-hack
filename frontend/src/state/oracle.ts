import { signal } from '@preact/signals'

export interface AgentVerdict {
  agentId: string
  agentName: string
  verdict: 'responded' | 'passed' | 'skipped'
}

export interface OracleRound {
  round: number
  mode: string
  reasoning: string
  speakers: Array<{ agent_id: string; agent_name: string; hint: string }>
  verdicts: AgentVerdict[]
  grader?: { reasoning: string; done: boolean }
}

export interface OracleState {
  active: boolean
  directed: boolean
  directedAgent: string | null
  rounds: OracleRound[]
  summary: string | null
  topic: string | null
}

const INITIAL_STATE: OracleState = {
  active: false,
  directed: false,
  directedAgent: null,
  rounds: [],
  summary: null,
  topic: null,
}

export const oracleState = signal<OracleState>({ ...INITIAL_STATE })

export function startOracle(directed: boolean, directedAgent?: string) {
  oracleState.value = {
    ...INITIAL_STATE,
    active: true,
    directed,
    directedAgent: directedAgent ?? null,
    topic: oracleState.value.topic,
  }
}

export function addRound(round: Omit<OracleRound, 'verdicts' | 'grader'>) {
  const s = oracleState.value
  oracleState.value = {
    ...s,
    rounds: [...s.rounds, { ...round, verdicts: [] }],
  }
}

export function addVerdictToCurrentRound(verdict: AgentVerdict) {
  const s = oracleState.value
  const rounds = [...s.rounds]
  if (rounds.length === 0) return
  const last = { ...rounds[rounds.length - 1] }
  last.verdicts = [...last.verdicts, verdict]
  rounds[rounds.length - 1] = last
  oracleState.value = { ...s, rounds }
}

export function setGraderResult(round: number, reasoning: string, done: boolean) {
  const s = oracleState.value
  const rounds = s.rounds.map((r) =>
    r.round === round ? { ...r, grader: { reasoning, done } } : r
  )
  oracleState.value = { ...s, rounds }
}

export function setOracleSummary(content: string) {
  oracleState.value = { ...oracleState.value, summary: content }
}

export function setOracleTopic(topic: string) {
  oracleState.value = { ...oracleState.value, topic }
}

export function endOracle() {
  oracleState.value = { ...oracleState.value, active: false }
}

export function resetOracle() {
  oracleState.value = { ...INITIAL_STATE }
}

import type { ComponentChildren } from 'preact'

interface ButtonProps {
  children: ComponentChildren
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'danger'
  disabled?: boolean
  class?: string
}

const variants = {
  primary: 'bg-accent hover:bg-accent-hover text-white glow-accent',
  secondary: 'glass hover:bg-zinc-50 text-zinc-600',
  danger: 'bg-danger hover:bg-red-600 text-white',
}

export function Button({
  children,
  onClick,
  variant = 'primary',
  disabled = false,
  class: className = '',
}: ButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      class={`px-4 py-2 rounded-xl font-medium text-sm transition-all disabled:opacity-50 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

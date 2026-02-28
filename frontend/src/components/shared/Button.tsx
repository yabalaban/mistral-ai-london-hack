import type { ComponentChildren } from 'preact'

interface ButtonProps {
  children: ComponentChildren
  onClick?: () => void
  variant?: 'primary' | 'secondary' | 'danger'
  disabled?: boolean
  class?: string
}

const variants = {
  primary: 'bg-dc-blurple hover:bg-dc-blurple-hover text-white',
  secondary: 'bg-dc-secondary hover:bg-dc-tertiary text-dc-text-secondary',
  danger: 'bg-dc-red hover:bg-red-600 text-white',
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
      class={`px-4 py-2 rounded-md font-medium text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${variants[variant]} ${className}`}
    >
      {children}
    </button>
  )
}

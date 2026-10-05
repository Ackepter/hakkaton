import { cn } from '@/lib/utils'

const variants = {
  default: 'bg-primary/15 text-primary border-primary/30',
  secondary: 'bg-secondary text-secondary-foreground border-transparent',
  destructive: 'bg-destructive/15 text-destructive border-destructive/30',
  success: 'bg-success/15 text-success border-success/30',
  outline: 'bg-transparent text-foreground border-border',
}

export function Badge({ className, variant = 'default', ...props }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
        variants[variant],
        className
      )}
      {...props}
    />
  )
}

import { cn } from '@/lib/utils'

const base = 'h-9 rounded-md border border-input bg-background px-3 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:opacity-50'

export function Input({ className, ...props }) {
  return <input className={cn(base, className)} {...props} />
}

export function Select({ className, children, ...props }) {
  return (
    <select className={cn(base, 'cursor-pointer', className)} {...props}>
      {children}
    </select>
  )
}

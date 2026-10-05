import { cn } from '@/lib/utils'

export function Table({ className, ...props }) {
  return (
    <div className="w-full overflow-auto">
      <table className={cn('w-full text-sm border-collapse', className)} {...props} />
    </div>
  )
}

export function TableHeader({ className, ...props }) {
  return <thead className={cn('[&_tr]:border-b [&_tr]:border-border', className)} {...props} />
}

export function TableBody({ className, ...props }) {
  return <tbody className={cn('[&_tr:last-child]:border-0', className)} {...props} />
}

export function TableRow({ className, ...props }) {
  return <tr className={cn('border-b border-border/60 transition-colors hover:bg-accent/50', className)} {...props} />
}

export function TableHead({ className, ...props }) {
  return <th className={cn('h-9 px-3 text-left align-middle text-xs font-medium text-muted-foreground', className)} {...props} />
}

export function TableCell({ className, ...props }) {
  return <td className={cn('px-3 py-2 align-middle', className)} {...props} />
}

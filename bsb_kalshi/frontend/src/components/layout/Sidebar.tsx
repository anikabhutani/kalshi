import { NavLink } from 'react-router-dom'
import { Activity } from 'lucide-react'
import { NAV_ITEMS } from '@/lib/nav'
import { cn } from '@/lib/utils'

export function Sidebar() {
  return (
    <aside className="sticky top-0 flex h-screen w-16 shrink-0 flex-col border-r bg-surface lg:w-60">
      <div className="flex h-16 items-center gap-2.5 border-b px-4">
        <div className="flex size-8 items-center justify-center rounded-lg bg-primary/15 text-primary">
          <Activity className="size-4" />
        </div>
        <div className="hidden leading-tight lg:block">
          <div className="text-sm font-semibold tracking-tight">Kalshi Recon</div>
          <div className="text-[11px] text-muted-foreground">Testing Kalshi’s data</div>
        </div>
      </div>
      <nav className="flex flex-1 flex-col gap-1 overflow-y-auto p-2">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.path}
            to={item.path}
            end={item.path === '/'}
            title={item.label}
            className={({ isActive }) =>
              cn(
                'group flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
                isActive && 'bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary',
              )
            }
          >
            <item.icon className="size-4 shrink-0" />
            <span className="hidden truncate lg:inline">{item.label}</span>
            {item.module !== null && (
              <span className="ml-auto hidden font-mono text-[10px] text-muted-foreground/70 lg:inline">
                {item.module}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
      <div className="hidden border-t p-4 text-[11px] leading-relaxed text-muted-foreground lg:block">
        Read-only: this tool only looks at data. It cannot place bets, move money, or change any account, and it
        never writes conclusions for you.
      </div>
    </aside>
  )
}

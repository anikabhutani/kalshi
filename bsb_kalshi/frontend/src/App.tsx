import type { ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Sidebar } from '@/components/layout/Sidebar'
import { TopBar } from '@/components/layout/TopBar'
import { NAV_ITEMS } from '@/lib/nav'
import { DepthPage } from '@/pages/DepthPage'
import { EndpointsPage } from '@/pages/EndpointsPage'
import { EvidencePage } from '@/pages/EvidencePage'
import { HomePage } from '@/pages/HomePage'
import { InGamePage } from '@/pages/InGamePage'
import { LimitsPage } from '@/pages/LimitsPage'
import { RestWsPage } from '@/pages/RestWsPage'
import { SchemaPage } from '@/pages/SchemaPage'
import { SportsbookPage } from '@/pages/SportsbookPage'
import { Task3Page } from '@/pages/Task3Page'
import { Task4Page } from '@/pages/Task4Page'
import { TimestampsPage } from '@/pages/TimestampsPage'

const PAGES: Record<string, ReactElement> = {
  '/': <HomePage />,
  '/endpoints': <EndpointsPage />,
  '/schema': <SchemaPage />,
  '/timestamps': <TimestampsPage />,
  '/depth': <DepthPage />,
  '/limits': <LimitsPage />,
  '/rest-vs-ws': <RestWsPage />,
  '/sportsbook': <SportsbookPage />,
  '/task3': <Task3Page />,
  '/task4': <Task4Page />,
  '/ingame': <InGamePage />,
  '/evidence': <EvidencePage />,
}

export default function App() {
  return (
    <div className="flex min-h-screen">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1">
          <Routes>
            {NAV_ITEMS.map((item) => (
              <Route key={item.path} path={item.path} element={PAGES[item.path]} />
            ))}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </main>
      </div>
    </div>
  )
}

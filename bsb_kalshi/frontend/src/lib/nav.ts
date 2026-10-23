import {
  ArrowLeftRight,
  Clock,
  Database,
  FileDown,
  Gauge,
  History,
  House,
  ListTree,
  type LucideIcon,
  Receipt,
  Scale,
  Trophy,
} from 'lucide-react'
import type { QuestionId } from '@/lib/api'

export interface NavItem {
  path: string
  label: string
  module: string | null
  icon: LucideIcon
  questions: QuestionId[]
  description: string
}

export const NAV_ITEMS: NavItem[] = [
  {
    path: '/',
    label: 'Home',
    module: null,
    icon: House,
    questions: [],
    description:
      'A tool that asks Kalshi for real data, keeps a receipt of every request, and shows the results as tables and charts, one page per research question.',
  },
  {
    path: '/endpoints',
    label: 'What data is available',
    module: 'M1',
    icon: ListTree,
    questions: ['Q4', 'Q5'],
    description:
      'Lists every type of data Kalshi offers, then tries each one without our account key and with it, to see which data is free for anyone and which needs an account.',
  },
  {
    path: '/schema',
    label: 'How data is organized',
    module: 'M2',
    icon: Database,
    questions: ['Q1'],
    description:
      'Downloads one real game and shows how Kalshi structures it: the league, the game, the yes/no bets inside it, and every piece of information attached to each.',
  },
  {
    path: '/timestamps',
    label: 'Price history & timing',
    module: 'M3',
    icon: Clock,
    questions: ['Q2'],
    description:
      'Downloads every kind of price history for one bet and checks how often a price is recorded, where the gaps are, and what the price was at any moment you pick.',
  },
  {
    path: '/depth',
    label: 'How far back data goes',
    module: 'M4',
    icon: History,
    questions: ['Q3'],
    description:
      'Searches backward in time to find the oldest data Kalshi still gives out, and checks which data has been moved into Kalshi’s archive for older games.',
  },
  {
    path: '/limits',
    label: 'Usage limits',
    module: 'M5',
    icon: Gauge,
    questions: ['Q4'],
    description:
      'Compares how much data Kalshi says we may request with what actually happens when we ask, and checks how large results are split into pages.',
  },
  {
    path: '/rest-vs-ws',
    label: 'Checking vs live stream',
    module: 'M6',
    icon: ArrowLeftRight,
    questions: ['Q6'],
    description:
      'Watches one live bet two ways at once, by asking for the price every few seconds and by receiving a live stream of every change, and counts what each method catches or misses.',
  },
  {
    path: '/sportsbook',
    label: 'Sportsbook comparison',
    module: 'M7',
    icon: Trophy,
    questions: [],
    description:
      'Upload sportsbook odds as a spreadsheet (CSV), turn them into win percentages, and lay them on top of the Kalshi price for the same game and time.',
  },
  {
    path: '/task3',
    label: 'Task 3',
    module: 'T3',
    icon: Receipt,
    questions: [],
    description:
      'What it costs to bet on Kalshi for every NFL game this season. Lists every game, spread and total-points bet since Sept 14, downloads minute-by-minute prices from opening to settlement, and works out the cost of a bet (half the gap between the buy and sell price, plus Kalshi’s fee) 24 hours, 3 hours, 1 hour and 15 minutes before kickoff.',
  },
  {
    path: '/task4',
    label: 'Task 4',
    module: 'T4',
    icon: Scale,
    questions: [],
    description:
      'What it costs to bet at DraftKings, FanDuel and Pinnacle for every NFL game of the 2025 and 2026 seasons, each season charted separately. Reads the sportsbook odds export, saves every game, and works out the vig and the expected cost of a $10 bet for every game, book, bet type and snapshot, with a quality check and charts. No requests are sent to Kalshi.',
  },
  {
    path: '/evidence',
    label: 'Report & export',
    module: 'M8',
    icon: FileDown,
    questions: ['Q1', 'Q2', 'Q3', 'Q4', 'Q5', 'Q6'],
    description:
      'Packages everything into one folder for the report: your written answers, the result tables, the charts, and the full list of requests sent to Kalshi.',
  },
]

/** Plain-language wording of the six research questions, shown instead of the backend's technical phrasing. */
export const QUESTION_PLAIN: Record<QuestionId, { title: string; prompt: string }> = {
  Q1: { title: 'How is the data organized?', prompt: 'How Kalshi groups sports data: leagues, games, and the yes/no bets inside each game.' },
  Q2: { title: 'Where do the times come from?', prompt: 'Which clock each price is stamped with, how precise it is, and how often prices are missing.' },
  Q3: { title: 'What is live and what is archived?', prompt: 'Which data is current, which has moved to the archive, and how far back we can still get it.' },
  Q4: { title: 'What are the practical limits?', prompt: 'Do we need an account key, how much can we request, and how are large results split into pages?' },
  Q5: { title: 'Which data matters for us?', prompt: 'Which of Kalshi’s data feeds help compare Kalshi prices with sportsbook odds.' },
  Q6: { title: 'Checking vs live stream', prompt: 'Is it better to ask for the price every few seconds, or to receive a live stream of every change?' },
}

export function navItem(path: string): NavItem {
  const item = NAV_ITEMS.find((n) => n.path === path)
  if (item === undefined) throw new Error(`No nav item for ${path}`)
  return item
}

export const MODULE_LABELS: Record<string, string> = Object.fromEntries(
  NAV_ITEMS.filter((n) => n.module !== null).map((n) => [n.module, n.label]),
)

import { useState, type ReactNode } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Settings } from 'lucide-react'
import { toast } from 'sonner'
import { api, type Meta, type RuntimeSettings } from '@/lib/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { NativeSelect } from '@/components/NativeSelect'

function todayIso(): string {
  const now = new Date()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

function Field({ label, hint, htmlFor, children }: { label: string; hint?: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="grid gap-1.5">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
      {hint !== undefined && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function SettingsForm({ meta, onSaved }: { meta: Meta; onSaved: () => void }) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<RuntimeSettings>(meta.settings)
  const set = <K extends keyof RuntimeSettings>(key: K, value: RuntimeSettings[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const save = useMutation({
    mutationFn: () => api.updateSettings(form),
    onSuccess: () => {
      toast.success('Settings saved.')
      void queryClient.invalidateQueries({ queryKey: ['meta'] })
      void queryClient.invalidateQueries({ queryKey: ['status'] })
      void queryClient.invalidateQueries({ queryKey: ['m5-doc'] })
      void queryClient.invalidateQueries({ queryKey: ['m8-summary'] })
      onSaved()
    },
  })

  const specVersion = meta.openapi.version

  return (
    <form
      className="grid gap-5"
      onSubmit={(e) => {
        e.preventDefault()
        save.mutate()
      }}
    >
      <div className="grid gap-4 rounded-lg border p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Evidence metadata</div>
        <Field
          label="API version (confirmed by you)"
          htmlFor="api_version"
          hint={`specs/openapi.yaml declares info.version = ${specVersion}. Confirm it matches the docs you checked.`}
        >
          <div className="flex gap-2">
            <Input
              id="api_version"
              value={form.api_version ?? ''}
              placeholder="not confirmed"
              onChange={(e) => set('api_version', e.target.value || null)}
            />
            <Button type="button" variant="outline" onClick={() => set('api_version', specVersion)}>
              Use {specVersion}
            </Button>
          </div>
        </Field>
        <Field label="Date checked" htmlFor="date_checked">
          <div className="flex gap-2">
            <Input
              id="date_checked"
              type="date"
              value={form.date_checked ?? ''}
              onChange={(e) => set('date_checked', e.target.value || null)}
            />
            <Button type="button" variant="outline" onClick={() => set('date_checked', todayIso())}>
              Today
            </Button>
          </div>
        </Field>
      </div>

      <div className="grid gap-4 rounded-lg border p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Connection</div>
        <Field label="Base URL" htmlFor="base_url" hint="Only servers listed in specs/openapi.yaml. Production keys only work on production hosts.">
          <NativeSelect id="base_url" value={form.base_url} onChange={(e) => set('base_url', e.target.value)}>
            {meta.openapi.servers.map((s) => (
              <option key={s.url} value={s.url}>
                {s.url} ({s.description})
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field label="Connection check endpoint" htmlFor="auth_check_path" hint="Authenticated GET endpoints from the spec that need no IDs.">
          <NativeSelect
            id="auth_check_path"
            value={form.auth_check_path}
            onChange={(e) => set('auth_check_path', e.target.value)}
          >
            {meta.auth_check_choices.map((p) => (
              <option key={p} value={p}>
                GET {p}
              </option>
            ))}
          </NativeSelect>
        </Field>
      </div>

      <div className="grid gap-4 rounded-lg border p-4">
        <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Politeness</div>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Requests / sec" htmlFor="rps">
            <Input
              id="rps"
              type="number"
              step="0.1"
              min="0.1"
              max="20"
              value={form.rate_limit_rps}
              onChange={(e) => set('rate_limit_rps', Number(e.target.value))}
            />
          </Field>
          <Field label="Burst" htmlFor="burst">
            <Input
              id="burst"
              type="number"
              min="1"
              max="50"
              value={form.rate_limit_burst}
              onChange={(e) => set('rate_limit_burst', Number(e.target.value))}
            />
          </Field>
          <Field label="Max req / job" htmlFor="max_requests">
            <Input
              id="max_requests"
              type="number"
              min="1"
              max="5000"
              value={form.max_requests_per_job}
              onChange={(e) => set('max_requests_per_job', Number(e.target.value))}
            />
          </Field>
        </div>
        <p className="text-xs text-muted-foreground">
          One request is in flight at a time. Jobs stop at the first HTTP 429.
        </p>
      </div>

      <DialogFooter>
        <Button type="submit" disabled={save.isPending}>
          Save settings
        </Button>
      </DialogFooter>
    </form>
  )
}

export function SettingsDialog({ meta }: { meta: Meta | undefined }) {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger render={<Button variant="ghost" size="icon" aria-label="Settings" disabled={meta === undefined} />}>
        <Settings />
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
          <DialogDescription>
            Stored locally in SQLite. Credentials are read from .env by the backend and are never shown here.
          </DialogDescription>
        </DialogHeader>
        {meta !== undefined && open && <SettingsForm meta={meta} onSaved={() => setOpen(false)} />}
      </DialogContent>
    </Dialog>
  )
}

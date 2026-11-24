import { useMutation, useQueryClient } from '@tanstack/react-query'
import { OctagonX } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'

export function StopAllButton() {
  const queryClient = useQueryClient()
  const stopAll = useMutation({
    mutationFn: api.stopAllJobs,
    onSuccess: ({ stopped }) => {
      toast.success(stopped === 0 ? 'No tests were running.' : `Stopped ${stopped} test${stopped === 1 ? '' : 's'}.`)
      void queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  return (
    <Button
      onClick={() => stopAll.mutate()}
      disabled={stopAll.isPending}
      className="bg-destructive text-white hover:bg-destructive/85"
    >
      <OctagonX />
      <span className="hidden sm:inline">Stop all tests</span>
    </Button>
  )
}

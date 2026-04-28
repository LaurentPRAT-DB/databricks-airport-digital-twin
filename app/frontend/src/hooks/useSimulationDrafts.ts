import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

export interface SimulationDraft {
  name: string;
  display_name: string;
  airport: string;
  arrivals: number;
  departures: number;
  duration_hours: number;
  time_step_seconds: number;
  seed: number | null;
  scenario_name: string | null;
  custom_scenario: {
    name: string;
    description: string;
    weather_events: Record<string, unknown>[];
    runway_events: Record<string, unknown>[];
    ground_events: Record<string, unknown>[];
    traffic_modifiers: Record<string, unknown>[];
  } | null;
  skip_positions: boolean;
  created_at: string;
  updated_at: string;
}

export type SaveDraftParams = Omit<SimulationDraft, 'name' | 'created_at' | 'updated_at'>;

async function fetchDrafts(): Promise<SimulationDraft[]> {
  const res = await fetch('/api/simulation/drafts');
  if (!res.ok) throw new Error('Failed to fetch drafts');
  const data = await res.json();
  return data.drafts ?? [];
}

async function saveDraft(params: SaveDraftParams): Promise<SimulationDraft> {
  const res = await fetch('/api/simulation/drafts', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Failed to save draft');
  }
  return res.json();
}

async function updateDraft({ name, ...params }: SaveDraftParams & { name: string }): Promise<SimulationDraft> {
  const res = await fetch(`/api/simulation/drafts/${encodeURIComponent(name)}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Failed to update draft');
  }
  return res.json();
}

async function deleteDraft(name: string): Promise<void> {
  const res = await fetch(`/api/simulation/drafts/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Failed to delete draft');
  }
}

export function useSimulationDrafts() {
  const queryClient = useQueryClient();
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['simulation-drafts'] });

  const { data: drafts = [], isLoading: isLoadingDrafts } = useQuery<SimulationDraft[], Error>({
    queryKey: ['simulation-drafts'],
    queryFn: fetchDrafts,
    staleTime: 30000,
    retry: 1,
  });

  const saveMutation = useMutation({ mutationFn: saveDraft, onSuccess: invalidate });
  const updateMutation = useMutation({ mutationFn: updateDraft, onSuccess: invalidate });
  const deleteMutation = useMutation({ mutationFn: deleteDraft, onSuccess: invalidate });

  return {
    drafts,
    isLoadingDrafts,
    saveDraft: saveMutation.mutateAsync,
    isSaving: saveMutation.isPending,
    updateDraft: updateMutation.mutateAsync,
    isUpdating: updateMutation.isPending,
    deleteDraft: deleteMutation.mutateAsync,
    isDeleting: deleteMutation.isPending,
  };
}

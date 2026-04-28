import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

export interface SimulationJob {
  run_id: number;
  status: string;
  airport: string;
  run_name: string;
  start_time: number | null;
  end_time: number | null;
  elapsed_seconds: number | null;
  run_page_url: string | null;
  output_file: string | null;
}

export interface ScenarioInfo {
  filename: string;
  name: string;
  description: string;
}

export interface CreateSimulationParams {
  airport: string;
  arrivals: number;
  departures: number;
  duration_hours: number;
  time_step_seconds: number;
  seed?: number;
  scenario_name?: string;
  custom_scenario?: {
    name: string;
    description: string;
    weather_events: Record<string, unknown>[];
    runway_events: Record<string, unknown>[];
    ground_events: Record<string, unknown>[];
    traffic_modifiers: Record<string, unknown>[];
  };
  skip_positions: boolean;
}

async function fetchJobs(): Promise<SimulationJob[]> {
  const res = await fetch('/api/simulation/jobs');
  if (!res.ok) throw new Error('Failed to fetch simulation jobs');
  const data = await res.json();
  return data.jobs ?? [];
}

async function fetchScenarios(): Promise<ScenarioInfo[]> {
  const res = await fetch('/api/simulation/scenarios');
  if (!res.ok) throw new Error('Failed to fetch scenarios');
  const data = await res.json();
  return data.scenarios ?? [];
}

async function createJob(params: CreateSimulationParams): Promise<{ run_id: number }> {
  const res = await fetch('/api/simulation/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Failed to create simulation job');
  }
  return res.json();
}

const ACTIVE_STATUSES = ['PENDING', 'QUEUED', 'RUNNING', 'BLOCKED'];

export function useSimulationJobs() {
  const queryClient = useQueryClient();

  const { data: jobs = [], isLoading: isLoadingJobs, error: jobsError } = useQuery<SimulationJob[], Error>({
    queryKey: ['simulation-jobs'],
    queryFn: fetchJobs,
    refetchInterval: (query) => {
      const data = query.state.data;
      const hasActive = data?.some(j => ACTIVE_STATUSES.includes(j.status));
      return hasActive ? 10000 : false;
    },
    staleTime: 5000,
    retry: 1,
  });

  const { data: scenarios = [], isLoading: isLoadingScenarios } = useQuery<ScenarioInfo[], Error>({
    queryKey: ['simulation-scenarios'],
    queryFn: fetchScenarios,
    staleTime: 300000,
    retry: 1,
  });

  const createMutation = useMutation({
    mutationFn: createJob,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['simulation-jobs'] });
    },
  });

  return {
    jobs,
    isLoadingJobs,
    jobsError,
    scenarios,
    isLoadingScenarios,
    createJob: createMutation.mutateAsync,
    isCreating: createMutation.isPending,
    createError: createMutation.error,
  };
}

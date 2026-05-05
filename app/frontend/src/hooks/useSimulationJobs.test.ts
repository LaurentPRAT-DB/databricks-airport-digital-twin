import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { useSimulationJobs, fetchScenarioDetail } from './useSimulationJobs';
import type { SimulationJob, ScenarioInfo, CreateSimulationParams } from './useSimulationJobs';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

const mockJob: SimulationJob = {
  run_id: 12345,
  status: 'TERMINATED',
  airport: 'KJFK',
  run_name: 'sim-kjfk-20260101',
  start_time: 1704067200000,
  end_time: 1704070800000,
  elapsed_seconds: 3600,
  run_page_url: 'https://example.com/run/12345',
  output_file: '/Volumes/catalog/schema/volume/sim.json',
};

const mockScenario: ScenarioInfo = {
  filename: 'thunderstorm.yaml',
  name: 'Thunderstorm',
  description: 'Severe weather causing runway closures',
};

const mockCreateParams: CreateSimulationParams = {
  airport: 'KLAX',
  arrivals: 10,
  departures: 10,
  duration_hours: 2,
  time_step_seconds: 30,
  seed: 42,
  run_name: 'test-sim',
  skip_positions: false,
};

const originalFetch = globalThis.fetch;

beforeEach(() => {
  globalThis.fetch = vi.fn();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function mockFetchResponse(body: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
  } as Response);
}

describe('useSimulationJobs', () => {
  describe('initial load', () => {
    it('fetches jobs and scenarios on mount', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
        if (url === '/api/simulation/jobs') {
          return mockFetchResponse({ jobs: [mockJob] });
        }
        if (url === '/api/simulation/scenarios') {
          return mockFetchResponse({ scenarios: [mockScenario] });
        }
        return mockFetchResponse({});
      });

      const { result } = renderHook(() => useSimulationJobs(), {
        wrapper: createWrapper(),
      });

      expect(result.current.isLoadingJobs).toBe(true);

      await waitFor(() => {
        expect(result.current.isLoadingJobs).toBe(false);
        expect(result.current.isLoadingScenarios).toBe(false);
      });

      expect(result.current.jobs).toEqual([mockJob]);
      expect(result.current.scenarios).toEqual([mockScenario]);
      expect(result.current.jobsError).toBeNull();
    });

    it('returns empty arrays when API returns no data', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
        if (url === '/api/simulation/jobs') {
          return mockFetchResponse({ jobs: [] });
        }
        if (url === '/api/simulation/scenarios') {
          return mockFetchResponse({ scenarios: [] });
        }
        return mockFetchResponse({});
      });

      const { result } = renderHook(() => useSimulationJobs(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingJobs).toBe(false);
      });

      expect(result.current.jobs).toEqual([]);
      expect(result.current.scenarios).toEqual([]);
    });

    it('exposes jobsError on fetch failure', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
        if (url === '/api/simulation/jobs') {
          return mockFetchResponse(null, false, 500);
        }
        if (url === '/api/simulation/scenarios') {
          return mockFetchResponse({ scenarios: [] });
        }
        return mockFetchResponse({});
      });

      const { result } = renderHook(() => useSimulationJobs(), {
        wrapper: createWrapper(),
      });

      // Hook has retry: 1 so it retries once before surfacing error
      await waitFor(() => {
        expect(result.current.jobsError).toBeInstanceOf(Error);
      }, { timeout: 5000 });

      expect(result.current.jobsError?.message).toBe('Failed to fetch simulation jobs');
    });
  });

  describe('createJob mutation', () => {
    it('POSTs to /api/simulation/jobs with correct body', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: RequestInit) => {
        if (url === '/api/simulation/jobs' && opts?.method === 'POST') {
          return mockFetchResponse({ run_id: 99999 });
        }
        if (url === '/api/simulation/jobs') {
          return mockFetchResponse({ jobs: [] });
        }
        if (url === '/api/simulation/scenarios') {
          return mockFetchResponse({ scenarios: [] });
        }
        return mockFetchResponse({});
      });

      const { result } = renderHook(() => useSimulationJobs(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingJobs).toBe(false);
      });

      let response: { run_id: number } | undefined;
      await act(async () => {
        response = await result.current.createJob(mockCreateParams);
      });

      expect(response?.run_id).toBe(99999);

      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const postCall = calls.find(
        (c) => c[1]?.method === 'POST' && c[0] === '/api/simulation/jobs'
      );
      expect(postCall).toBeDefined();
      expect(JSON.parse(postCall![1].body)).toEqual(mockCreateParams);
      expect(postCall![1].headers['Content-Type']).toBe('application/json');
    });

    it('throws on error response with detail message', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: RequestInit) => {
        if (url === '/api/simulation/jobs' && opts?.method === 'POST') {
          return mockFetchResponse({ detail: 'Cluster quota exceeded' }, false, 429);
        }
        if (url === '/api/simulation/jobs') {
          return mockFetchResponse({ jobs: [] });
        }
        if (url === '/api/simulation/scenarios') {
          return mockFetchResponse({ scenarios: [] });
        }
        return mockFetchResponse({});
      });

      const { result } = renderHook(() => useSimulationJobs(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingJobs).toBe(false);
      });

      await expect(
        act(async () => {
          await result.current.createJob(mockCreateParams);
        })
      ).rejects.toThrow('Cluster quota exceeded');
    });

    it('sets createError after mutation failure', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: RequestInit) => {
        if (url === '/api/simulation/jobs' && opts?.method === 'POST') {
          return mockFetchResponse({ detail: 'Server error' }, false, 500);
        }
        if (url === '/api/simulation/jobs') {
          return mockFetchResponse({ jobs: [] });
        }
        if (url === '/api/simulation/scenarios') {
          return mockFetchResponse({ scenarios: [] });
        }
        return mockFetchResponse({});
      });

      const { result } = renderHook(() => useSimulationJobs(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingJobs).toBe(false);
      });

      // mutateAsync rejects — catch it so the test doesn't fail on rejection
      await act(async () => {
        try {
          await result.current.createJob(mockCreateParams);
        } catch {
          // expected rejection
        }
      });

      // React Query sets mutation.error after state updates settle
      await waitFor(() => {
        expect(result.current.createError).toBeInstanceOf(Error);
      });
      expect(result.current.createError?.message).toBe('Server error');
    });
  });

  describe('deleteJob mutation', () => {
    it('DELETEs to /api/simulation/jobs/{run_id}', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: RequestInit) => {
        if (url === '/api/simulation/jobs/12345' && opts?.method === 'DELETE') {
          return mockFetchResponse({ deleted: 12345, was_cancelled: false });
        }
        if (url === '/api/simulation/jobs') {
          return mockFetchResponse({ jobs: [mockJob] });
        }
        if (url === '/api/simulation/scenarios') {
          return mockFetchResponse({ scenarios: [] });
        }
        return mockFetchResponse({});
      });

      const { result } = renderHook(() => useSimulationJobs(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingJobs).toBe(false);
      });

      let response: { deleted: number; was_cancelled: boolean } | undefined;
      await act(async () => {
        response = await result.current.deleteJob(12345);
      });

      expect(response).toEqual({ deleted: 12345, was_cancelled: false });

      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const deleteCall = calls.find((c) => c[1]?.method === 'DELETE');
      expect(deleteCall).toBeDefined();
      expect(deleteCall![0]).toBe('/api/simulation/jobs/12345');
    });

    it('throws on error response', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: RequestInit) => {
        if (opts?.method === 'DELETE') {
          return mockFetchResponse({ detail: 'Job not found' }, false, 404);
        }
        if (url === '/api/simulation/jobs') {
          return mockFetchResponse({ jobs: [] });
        }
        if (url === '/api/simulation/scenarios') {
          return mockFetchResponse({ scenarios: [] });
        }
        return mockFetchResponse({});
      });

      const { result } = renderHook(() => useSimulationJobs(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingJobs).toBe(false);
      });

      await expect(
        act(async () => {
          await result.current.deleteJob(99999);
        })
      ).rejects.toThrow('Job not found');
    });
  });

  describe('cache invalidation', () => {
    it('refetches jobs after createJob succeeds', async () => {
      let jobCallCount = 0;
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string, opts?: RequestInit) => {
        if (url === '/api/simulation/jobs' && opts?.method === 'POST') {
          return mockFetchResponse({ run_id: 99999 });
        }
        if (url === '/api/simulation/jobs') {
          jobCallCount++;
          const jobs = jobCallCount > 1 ? [mockJob, { ...mockJob, run_id: 99999 }] : [mockJob];
          return mockFetchResponse({ jobs });
        }
        if (url === '/api/simulation/scenarios') {
          return mockFetchResponse({ scenarios: [] });
        }
        return mockFetchResponse({});
      });

      const { result } = renderHook(() => useSimulationJobs(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingJobs).toBe(false);
      });

      expect(result.current.jobs).toHaveLength(1);

      await act(async () => {
        await result.current.createJob(mockCreateParams);
      });

      await waitFor(() => {
        expect(result.current.jobs).toHaveLength(2);
      });
    });
  });
});

describe('fetchScenarioDetail', () => {
  beforeEach(() => {
    globalThis.fetch = vi.fn();
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  it('fetches scenario detail by filename', async () => {
    const detail = {
      filename: 'thunderstorm.yaml',
      name: 'Thunderstorm',
      description: 'Severe weather',
      weather_events: [{ type: 'storm', start: 0.5, end: 1.0 }],
      runway_events: [],
      ground_events: [],
      traffic_modifiers: [],
    };

    (globalThis.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      mockFetchResponse(detail)
    );

    const result = await fetchScenarioDetail('thunderstorm.yaml');

    expect(result).toEqual(detail);
    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/simulation/scenarios/thunderstorm.yaml'
    );
  });

  it('encodes filename in URL', async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      mockFetchResponse({ filename: 'file with spaces.yaml', name: 'Test', description: '', weather_events: [], runway_events: [], ground_events: [], traffic_modifiers: [] })
    );

    await fetchScenarioDetail('file with spaces.yaml');

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/simulation/scenarios/file%20with%20spaces.yaml'
    );
  });

  it('throws on error response', async () => {
    (globalThis.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
      mockFetchResponse(null, false, 404)
    );

    await expect(fetchScenarioDetail('missing.yaml')).rejects.toThrow(
      'Failed to fetch scenario detail'
    );
  });
});

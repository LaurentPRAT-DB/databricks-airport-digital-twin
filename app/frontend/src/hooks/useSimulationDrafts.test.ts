import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { useSimulationDrafts } from './useSimulationDrafts';
import type { SimulationDraft, SaveDraftParams } from './useSimulationDrafts';

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: queryClient }, children);
}

const mockDraft: SimulationDraft = {
  name: 'test-draft',
  display_name: 'Test Draft',
  airport: 'KJFK',
  arrivals: 10,
  departures: 10,
  duration_hours: 2,
  time_step_seconds: 30,
  seed: 42,
  scenario_name: null,
  custom_scenario: null,
  skip_positions: false,
  run_id: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const mockSaveParams: SaveDraftParams = {
  display_name: 'New Draft',
  airport: 'KLAX',
  arrivals: 5,
  departures: 5,
  duration_hours: 1,
  time_step_seconds: 30,
  seed: null,
  scenario_name: null,
  custom_scenario: null,
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

describe('useSimulationDrafts', () => {
  describe('initial load', () => {
    it('fetches drafts on mount and returns them', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
        mockFetchResponse({ drafts: [mockDraft] })
      );

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      expect(result.current.isLoadingDrafts).toBe(true);

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      expect(result.current.drafts).toEqual([mockDraft]);
      expect(globalThis.fetch).toHaveBeenCalledWith('/api/simulation/drafts');
    });

    it('returns empty array when response has no drafts', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>).mockReturnValue(
        mockFetchResponse({ drafts: [] })
      );

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      expect(result.current.drafts).toEqual([]);
    });
  });

  describe('saveDraft mutation', () => {
    it('POSTs to /api/simulation/drafts with correct body', async () => {
      const savedDraft = { ...mockDraft, name: 'new-draft', display_name: 'New Draft' };
      (globalThis.fetch as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(mockFetchResponse({ drafts: [] }))
        .mockReturnValueOnce(mockFetchResponse(savedDraft))
        .mockReturnValueOnce(mockFetchResponse({ drafts: [savedDraft] }));

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      await act(async () => {
        await result.current.saveDraft(mockSaveParams);
      });

      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const postCall = calls.find(
        (c) => c[1]?.method === 'POST' && c[0] === '/api/simulation/drafts'
      );
      expect(postCall).toBeDefined();
      expect(JSON.parse(postCall![1].body)).toEqual(mockSaveParams);
      expect(postCall![1].headers['Content-Type']).toBe('application/json');
    });

    it('throws on error response with detail message', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(mockFetchResponse({ drafts: [] }))
        .mockReturnValueOnce(mockFetchResponse({ detail: 'Name already exists' }, false, 409));

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      await expect(
        act(async () => {
          await result.current.saveDraft(mockSaveParams);
        })
      ).rejects.toThrow('Name already exists');
    });
  });

  describe('updateDraft mutation', () => {
    it('PUTs to /api/simulation/drafts/{name} with correct body', async () => {
      const updatedDraft = { ...mockDraft, arrivals: 20 };
      (globalThis.fetch as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(mockFetchResponse({ drafts: [mockDraft] }))
        .mockReturnValueOnce(mockFetchResponse(updatedDraft))
        .mockReturnValueOnce(mockFetchResponse({ drafts: [updatedDraft] }));

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      await act(async () => {
        await result.current.updateDraft({ name: 'test-draft', ...mockSaveParams });
      });

      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const putCall = calls.find((c) => c[1]?.method === 'PUT');
      expect(putCall).toBeDefined();
      expect(putCall![0]).toBe('/api/simulation/drafts/test-draft');
      const body = JSON.parse(putCall![1].body);
      expect(body.name).toBeUndefined();
      expect(body.display_name).toBe('New Draft');
    });

    it('throws on error response', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(mockFetchResponse({ drafts: [] }))
        .mockReturnValueOnce(mockFetchResponse({ detail: 'Draft not found' }, false, 404));

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      await expect(
        act(async () => {
          await result.current.updateDraft({ name: 'missing', ...mockSaveParams });
        })
      ).rejects.toThrow('Draft not found');
    });
  });

  describe('deleteDraft mutation', () => {
    it('DELETEs to /api/simulation/drafts/{name}', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(mockFetchResponse({ drafts: [mockDraft] }))
        .mockReturnValueOnce(mockFetchResponse(undefined, true, 204))
        .mockReturnValueOnce(mockFetchResponse({ drafts: [] }));

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      await act(async () => {
        await result.current.deleteDraft('test-draft');
      });

      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const deleteCall = calls.find((c) => c[1]?.method === 'DELETE');
      expect(deleteCall).toBeDefined();
      expect(deleteCall![0]).toBe('/api/simulation/drafts/test-draft');
    });

    it('throws on error response', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(mockFetchResponse({ drafts: [] }))
        .mockReturnValueOnce(mockFetchResponse({ detail: 'Cannot delete running draft' }, false, 400));

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      await expect(
        act(async () => {
          await result.current.deleteDraft('test-draft');
        })
      ).rejects.toThrow('Cannot delete running draft');
    });
  });

  describe('runDraft mutation', () => {
    it('POSTs to /api/simulation/drafts/{name}/run', async () => {
      const runningDraft = { ...mockDraft, run_id: 123 };
      (globalThis.fetch as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(mockFetchResponse({ drafts: [mockDraft] }))
        .mockReturnValueOnce(mockFetchResponse(runningDraft))
        .mockReturnValueOnce(mockFetchResponse({ drafts: [runningDraft] }));

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      let response: SimulationDraft | undefined;
      await act(async () => {
        response = await result.current.runDraft('test-draft');
      });

      expect(response?.run_id).toBe(123);

      const calls = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls;
      const runCall = calls.find(
        (c) => c[1]?.method === 'POST' && String(c[0]).includes('/run')
      );
      expect(runCall).toBeDefined();
      expect(runCall![0]).toBe('/api/simulation/drafts/test-draft/run');
    });

    it('throws on error response', async () => {
      (globalThis.fetch as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(mockFetchResponse({ drafts: [] }))
        .mockReturnValueOnce(mockFetchResponse({ detail: 'Simulation cluster unavailable' }, false, 503));

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      await expect(
        act(async () => {
          await result.current.runDraft('test-draft');
        })
      ).rejects.toThrow('Simulation cluster unavailable');
    });
  });

  describe('cache invalidation', () => {
    it('refetches drafts after saveDraft succeeds', async () => {
      const newDraft = { ...mockDraft, name: 'new' };
      (globalThis.fetch as ReturnType<typeof vi.fn>)
        .mockReturnValueOnce(mockFetchResponse({ drafts: [] }))
        .mockReturnValueOnce(mockFetchResponse(newDraft))
        .mockReturnValueOnce(mockFetchResponse({ drafts: [newDraft] }));

      const { result } = renderHook(() => useSimulationDrafts(), {
        wrapper: createWrapper(),
      });

      await waitFor(() => {
        expect(result.current.isLoadingDrafts).toBe(false);
      });

      await act(async () => {
        await result.current.saveDraft(mockSaveParams);
      });

      await waitFor(() => {
        expect(result.current.drafts).toEqual([newDraft]);
      });
    });
  });
});

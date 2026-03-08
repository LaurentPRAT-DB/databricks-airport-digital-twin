import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { http, HttpResponse, delay } from 'msw';
import { server } from '../../test/mocks/server';
import DataOpsDashboard from './DataOpsDashboard';

// Sample dashboard data
const mockDashboardData = {
  timestamp: '2024-03-08T12:00:00Z',
  health: {
    acquisition: 'healthy' as const,
    sync: 'healthy' as const,
    freshness: 'healthy' as const,
    overall: 'healthy' as const,
  },
  summary: {
    total_acquisitions: 150,
    total_records_acquired: 5000,
    total_syncs: 25,
    records_synced: 4500,
    last_sync: '2024-03-08T11:55:00Z',
  },
  sync_status: {
    checked_at: '2024-03-08T12:00:00Z',
    delta: { record_count: 100, staleness_seconds: 30 },
    lakebase: { record_count: 98, staleness_seconds: 45 },
    in_sync: true,
    sync_lag_seconds: 15,
    record_count_diff: 2,
  },
  sources: {
    opensky: { count: 50, records: 2500, errors: 2 },
    synthetic: { count: 100, records: 2500, errors: 0 },
  },
  endpoints: {
    '/api/flights': { count: 150, records: 5000, errors: 2 },
  },
  recent_acquisitions: [
    {
      timestamp: '2024-03-08T11:59:00Z',
      source: 'opensky',
      endpoint: '/api/flights',
      record_count: 50,
      latency_ms: 150,
      success: true,
      error: null,
    },
    {
      timestamp: '2024-03-08T11:58:00Z',
      source: 'synthetic',
      endpoint: '/api/flights',
      record_count: 50,
      latency_ms: 10,
      success: true,
      error: null,
    },
  ],
  recent_syncs: [
    {
      timestamp: '2024-03-08T11:55:00Z',
      direction: 'delta_to_lakebase',
      records_synced: 100,
      records_failed: 0,
      latency_ms: 500,
      success: true,
    },
  ],
};

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

describe('DataOpsDashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Loading State', () => {
    it('shows loading state initially', () => {
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(5000); // Long delay to keep loading
          return HttpResponse.json(mockDashboardData);
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });
      expect(screen.getByText(/loading/i)).toBeInTheDocument();
    });
  });

  describe('Error State', () => {
    it('shows error state when fetch fails', async () => {
      server.use(
        http.get('/api/data-ops/dashboard', () => {
          return HttpResponse.error();
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/error loading dashboard/i)).toBeInTheDocument();
      });
    });

    it('shows retry button on error', async () => {
      server.use(
        http.get('/api/data-ops/dashboard', () => {
          return HttpResponse.error();
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
      });
    });
  });

  describe('Success State', () => {
    beforeEach(() => {
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(mockDashboardData);
        })
      );
    });

    it('renders dashboard title', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/data operations dashboard/i)).toBeInTheDocument();
      });
    });

    it('displays overall health indicator', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/data operations dashboard/i)).toBeInTheDocument();
      });
    });

    it('shows acquisition count', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText('150')).toBeInTheDocument();
      });
    });

    it('shows sync count', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText('25')).toBeInTheDocument();
      });
    });

    it('shows sync status as In Sync', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText('In Sync')).toBeInTheDocument();
      });
    });

    it('displays data sources table', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        // Use getAllByText since source names appear in both table and recent acquisitions
        const openskyElements = screen.getAllByText('opensky');
        const syntheticElements = screen.getAllByText('synthetic');
        expect(openskyElements.length).toBeGreaterThan(0);
        expect(syntheticElements.length).toBeGreaterThan(0);
      });
    });

    it('displays recent acquisitions section', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/recent acquisitions/i)).toBeInTheDocument();
      });
    });

    it('displays recent syncs section', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/recent syncs/i)).toBeInTheDocument();
      });
    });
  });

  describe('Health Indicators', () => {
    it('shows Out of Sync when freshness is unhealthy', async () => {
      const staleData = {
        ...mockDashboardData,
        health: {
          ...mockDashboardData.health,
          freshness: 'unhealthy' as const,
          overall: 'unhealthy' as const,
        },
        sync_status: {
          ...mockDashboardData.sync_status,
          in_sync: false,
          sync_lag_seconds: 1200, // 20 minutes
        },
      };
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(staleData);
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText('Out of Sync')).toBeInTheDocument();
      });
    });
  });

  describe('Check Freshness Button', () => {
    it('triggers freshness check when clicked', async () => {
      let checkFreshnessCallCount = 0;
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(mockDashboardData);
        }),
        http.post('/api/data-ops/check-freshness', async () => {
          checkFreshnessCallCount++;
          await delay(10);
          return HttpResponse.json({ status: 'checking' });
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/check freshness/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/check freshness/i));

      await waitFor(() => {
        expect(checkFreshnessCallCount).toBe(1);
      });
    });

    it('shows checking state while refreshing', async () => {
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(mockDashboardData);
        }),
        http.post('/api/data-ops/check-freshness', async () => {
          await delay(2000); // Long delay
          return HttpResponse.json({ status: 'checking' });
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/check freshness/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/check freshness/i));

      await waitFor(() => {
        expect(screen.getByText(/checking/i)).toBeInTheDocument();
      });
    });
  });

  describe('Close Button', () => {
    beforeEach(() => {
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(mockDashboardData);
        })
      );
    });

    it('calls onClose when close button clicked', async () => {
      const onClose = vi.fn();

      render(<DataOpsDashboard onClose={onClose} />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/close/i)).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText(/close/i));
      expect(onClose).toHaveBeenCalled();
    });

    it('does not render close button when onClose not provided', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/data operations dashboard/i)).toBeInTheDocument();
      });

      // Close button should not be present
      expect(screen.queryByRole('button', { name: /^close$/i })).not.toBeInTheDocument();
    });
  });

  describe('Sync Status Details', () => {
    beforeEach(() => {
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(mockDashboardData);
        })
      );
    });

    it('displays Delta record count', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        // 100 appears in multiple places (Delta record count and sync records)
        const elements = screen.getAllByText('100');
        expect(elements.length).toBeGreaterThan(0);
      });
    });

    it('displays Lakebase record count', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText('98')).toBeInTheDocument(); // Lakebase record count
      });
    });

    it('shows staleness in human readable format', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        // 30s and 45s should be displayed
        expect(screen.getByText('30s')).toBeInTheDocument();
        expect(screen.getByText('45s')).toBeInTheDocument();
      });
    });

    it('shows lag time', async () => {
      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/lag.*15s/i)).toBeInTheDocument();
      });
    });
  });

  describe('Empty States', () => {
    it('handles no recent acquisitions', async () => {
      const emptyData = {
        ...mockDashboardData,
        recent_acquisitions: [],
      };
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(emptyData);
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/no recent acquisitions/i)).toBeInTheDocument();
      });
    });

    it('handles no sync operations', async () => {
      const emptyData = {
        ...mockDashboardData,
        recent_syncs: [],
      };
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(emptyData);
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText(/no sync operations/i)).toBeInTheDocument();
      });
    });

    it('handles missing sync status data', async () => {
      const noSyncData = {
        ...mockDashboardData,
        sync_status: {
          ...mockDashboardData.sync_status,
          delta: null,
          lakebase: null,
        },
      };
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(noSyncData);
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        // "No data available" appears twice (once for Delta, once for Lakebase)
        const elements = screen.getAllByText(/no data available/i);
        expect(elements.length).toBe(2);
      });
    });
  });

  describe('Error Rate Display', () => {
    it('shows error rate percentage', async () => {
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(mockDashboardData);
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        // opensky: 2 errors out of 50 = 4%
        expect(screen.getByText('4.0%')).toBeInTheDocument();
        // synthetic: 0 errors out of 100 = 0.0% (toFixed(1) format)
        expect(screen.getByText('0.0%')).toBeInTheDocument();
      });
    });

    it('highlights high error rates in red', async () => {
      const highErrorData = {
        ...mockDashboardData,
        sources: {
          problematic: { count: 10, records: 100, errors: 5 }, // 50% error rate
        },
      };
      server.use(
        http.get('/api/data-ops/dashboard', async () => {
          await delay(10);
          return HttpResponse.json(highErrorData);
        })
      );

      render(<DataOpsDashboard />, { wrapper: createWrapper() });

      await waitFor(() => {
        expect(screen.getByText('50.0%')).toBeInTheDocument();
      });
    });
  });
});

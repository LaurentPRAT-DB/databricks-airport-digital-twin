import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SimulationReport } from './SimulationReport';
import type { UseSimulationReplayResult } from '../../hooks/useSimulationReplay';

let mockFlightContext = {
  filteredFlights: [] as { callsign?: string; icao24?: string }[],
  setSelectedFlight: vi.fn(),
};

vi.mock('../../context/FlightContext', () => ({
  useFlightContext: () => mockFlightContext,
}));

const mockDownloadDataUrl = vi.fn();
vi.mock('../../utils/sceneCapture', () => ({
  captureCurrentView: vi.fn().mockResolvedValue(null),
  downloadDataUrl: (...args: unknown[]) => mockDownloadDataUrl(...args),
}));

function createMockSim(overrides: Partial<UseSimulationReplayResult> = {}): UseSimulationReplayResult {
  return {
    isActive: true,
    isPlaying: false,
    isLoading: false,
    isFetchingFiles: false,
    switchPaused: false,
    speed: 1 as const,
    currentFrameIndex: 5,
    totalFrames: 100,
    currentSimTime: '2026-04-15T12:00:00Z',
    flights: [],
    availableFiles: [],
    loadedFile: 'test_sim.json',
    summary: {
      total_flights: 45,
      arrivals: 20,
      departures: 25,
      on_time_pct: 82.5,
      schedule_delay_min: 8.2,
      total_cancellations: 2,
      total_go_arounds: 3,
      total_diversions: 1,
      peak_simultaneous_flights: 38,
      avg_capacity_hold_min: 4.1,
    },
    scenarioEvents: [
      { time: '2026-04-15T08:00:00Z', event_type: 'weather', description: 'Fog reduces visibility' },
      { time: '2026-04-15T09:30:00Z', event_type: 'go_around', description: 'UAL100 go-around #1 (altitude 3500ft)' },
      { time: '2026-04-15T10:15:00Z', event_type: 'runway', description: 'Runway 28R closed for maintenance' },
      { time: '2026-04-15T11:00:00Z', event_type: 'capacity', description: 'Arrival rate reduced to 30/hr' },
      { time: '2026-04-15T14:00:00Z', event_type: 'diversion', description: 'DAL200 diverted to OAK' },
    ],
    scenarioName: 'Test Scenario',
    airport: 'KSFO',
    simStartTime: '2026-04-15T06:00:00Z',
    simEndTime: '2026-04-15T18:00:00Z',
    loadFile: vi.fn().mockResolvedValue(undefined),
    loadDemo: vi.fn().mockResolvedValue(undefined),
    play: vi.fn(),
    pause: vi.fn(),
    togglePlayPause: vi.fn(),
    setSpeed: vi.fn(),
    seekTo: vi.fn(),
    seekToPercent: vi.fn(),
    seekToTime: vi.fn(),
    seekToFlight: vi.fn().mockReturnValue(true),
    stop: vi.fn(),
    fetchFiles: vi.fn().mockResolvedValue(undefined),
    pauseForSwitch: vi.fn(),
    ...overrides,
  };
}

describe('SimulationReport — extended interactions', () => {
  const onClose = vi.fn();
  let mockSim: UseSimulationReplayResult;

  beforeEach(() => {
    vi.clearAllMocks();
    mockSim = createMockSim();
    mockFlightContext = {
      filteredFlights: [
        { callsign: 'UAL100', icao24: 'abc001' },
        { callsign: 'DAL200', icao24: 'abc002' },
      ],
      setSelectedFlight: vi.fn(),
    };
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:test');
    globalThis.URL.revokeObjectURL = vi.fn();
  });

  describe('Tab switching', () => {
    it('switches between Dashboard and Analysis tabs', async () => {
      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      expect(screen.getByText('Dashboard')).toBeInTheDocument();
      expect(screen.getByText('Analysis Report')).toBeInTheDocument();
      expect(screen.getByText('On-Time')).toBeInTheDocument();

      fireEvent.click(screen.getByText('Analysis Report'));
      expect(screen.getByText('No analysis report available')).toBeInTheDocument();
    });

    it('shows markdown report content on Analysis tab when markdownReport exists', () => {
      const sim = createMockSim({ markdownReport: '## Summary\n\nThis is a test report' });
      render(<SimulationReport sim={sim} onClose={onClose} />);
      fireEvent.click(screen.getByText('Analysis Report'));
      expect(screen.getByText('Summary')).toBeInTheDocument();
    });

    it('shows blue dot indicator on Analysis tab when markdownReport is present', () => {
      const sim = createMockSim({ markdownReport: '## Report' });
      render(<SimulationReport sim={sim} onClose={onClose} />);
      const analysisBtn = screen.getByText('Analysis Report').closest('button')!;
      const dot = analysisBtn.querySelector('.bg-blue-500');
      expect(dot).toBeInTheDocument();
    });
  });

  describe('Generate Report button', () => {
    it('shows Generate Analysis Report button when no report exists', () => {
      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      fireEvent.click(screen.getByText('Analysis Report'));
      expect(screen.getByText('Generate Analysis Report')).toBeInTheDocument();
    });

    it('shows loading state while generating report', async () => {
      let resolveReq: (v: Response) => void;
      const fetchPromise = new Promise<Response>((resolve) => { resolveReq = resolve; });
      globalThis.fetch = vi.fn(() => fetchPromise) as unknown as typeof fetch;

      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      fireEvent.click(screen.getByText('Analysis Report'));
      fireEvent.click(screen.getByText('Generate Analysis Report'));

      await waitFor(() => {
        expect(screen.getByText('Generating Report...')).toBeInTheDocument();
      });

      resolveReq!(new Response(JSON.stringify({ content: '## Generated' }), { status: 200 }));
    });

    it('renders generated report after successful fetch (saved file)', async () => {
      globalThis.fetch = vi.fn(() =>
        Promise.resolve(new Response(JSON.stringify({ content: '## Generated Report\n\nContent here' }), { status: 200 }))
      ) as unknown as typeof fetch;

      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      fireEvent.click(screen.getByText('Analysis Report'));
      fireEvent.click(screen.getByText('Generate Analysis Report'));

      await waitFor(() => {
        expect(screen.getByText('Generated Report')).toBeInTheDocument();
      });
    });

    it('uses direct POST body for live/demo sims (no loadedFile)', async () => {
      const liveSim = createMockSim({ loadedFile: undefined });
      globalThis.fetch = vi.fn(() =>
        Promise.resolve(new Response(JSON.stringify({ content: '## Live report' }), { status: 200 }))
      ) as unknown as typeof fetch;

      render(<SimulationReport sim={liveSim} onClose={onClose} />);
      fireEvent.click(screen.getByText('Analysis Report'));
      fireEvent.click(screen.getByText('Generate Analysis Report'));

      await waitFor(() => {
        expect(globalThis.fetch).toHaveBeenCalledWith(
          '/api/simulation/report/generate',
          expect.objectContaining({ method: 'POST' })
        );
      });
    });

    it('shows error when report generation fails', async () => {
      globalThis.fetch = vi.fn(() =>
        Promise.resolve(new Response(JSON.stringify({ detail: 'Model unavailable' }), { status: 500 }))
      ) as unknown as typeof fetch;

      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      fireEvent.click(screen.getByText('Analysis Report'));
      fireEvent.click(screen.getByText('Generate Analysis Report'));

      await waitFor(() => {
        expect(screen.getByText('Model unavailable')).toBeInTheDocument();
      });
    });
  });

  describe('Download button', () => {
    it('calls downloadDataUrl with an HTML blob URL', () => {
      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      fireEvent.click(screen.getByText('Download Report'));
      expect(globalThis.URL.createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
      expect(mockDownloadDataUrl).toHaveBeenCalledWith(
        'blob:test',
        expect.stringContaining('report_KSFO_Test_Scenario_')
      );
      expect(globalThis.URL.revokeObjectURL).toHaveBeenCalledWith('blob:test');
    });
  });

  describe('Time filter', () => {
    it('filters events by hour range', async () => {
      const user = userEvent.setup();
      render(<SimulationReport sim={mockSim} onClose={onClose} />);

      // Default is 0-24, so weather (8:00), go_around (9:30), runway (10:15), diversion (14:00) are visible
      // (capacity excluded by type filter)
      expect(screen.getByText(/Fog reduces visibility/)).toBeInTheDocument();
      expect(screen.getByText(/DAL200 diverted/)).toBeInTheDocument();

      // Change fromHour to 10
      const inputs = screen.getAllByRole('spinbutton');
      const fromInput = inputs.find(i => (i as HTMLInputElement).value === '0');
      if (fromInput) {
        await user.clear(fromInput);
        await user.type(fromInput, '10');
        // After setting from=10, weather at 8:00 and go_around at 9:30 should be filtered out
        await waitFor(() => {
          expect(screen.queryByText(/Fog reduces visibility/)).not.toBeInTheDocument();
        });
      }
    });
  });

  describe('KPI help panel', () => {
    it('toggles KPI help panel on ? button click', () => {
      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      const helpBtn = screen.getByTitle('Explain KPIs');
      expect(screen.queryByText(/Percentage of flights operating/)).not.toBeInTheDocument();

      fireEvent.click(helpBtn);
      expect(screen.getByText(/Percentage of flights operating/)).toBeInTheDocument();

      fireEvent.click(helpBtn);
      expect(screen.queryByText(/Percentage of flights operating/)).not.toBeInTheDocument();
    });
  });

  describe('Fullscreen toggle', () => {
    it('toggles fullscreen class on modal', () => {
      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      const fullscreenBtn = screen.getByTitle('Fullscreen');
      const modal = fullscreenBtn.closest('.bg-white')!;

      expect(modal.className).toContain('w-[900px]');
      expect(modal.className).not.toContain('w-full h-full');

      fireEvent.click(fullscreenBtn);
      expect(modal.className).toContain('w-full');
      expect(modal.className).toContain('h-full');
    });
  });

  describe('Close button', () => {
    it('footer Close button calls onClose', () => {
      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      const closeBtn = screen.getByText('Close');
      fireEvent.click(closeBtn);
      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('Group by', () => {
    it('switches between Time, Category, and Flight grouping modes', () => {
      render(<SimulationReport sim={mockSim} onClose={onClose} />);
      // "Group By" buttons are in a flex container with border
      const groupByButtons = screen.getAllByRole('button').filter(btn =>
        btn.textContent === 'Time' || btn.textContent === 'Category' || btn.textContent === 'Flight'
      );
      expect(groupByButtons.length).toBe(3);

      const categoryBtn = groupByButtons.find(b => b.textContent === 'Category')!;
      fireEvent.click(categoryBtn);
      // Events should still be visible
      expect(screen.getByText(/Fog reduces visibility/)).toBeInTheDocument();

      const flightBtn = groupByButtons.find(b => b.textContent === 'Flight')!;
      fireEvent.click(flightBtn);
      // In flight mode, events are grouped by callsign
      expect(screen.getByText('UAL100')).toBeInTheDocument();
    });
  });
});

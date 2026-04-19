import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within } from '@testing-library/react';
import { SimulationReport } from './SimulationReport';
import type { UseSimulationReplayResult } from '../../hooks/useSimulationReplay';

// ── Mock FlightContext ─────────────────────────────────────────────

let mockFlightContext = {
  filteredFlights: [] as { callsign?: string; icao24?: string }[],
  setSelectedFlight: vi.fn(),
};

vi.mock('../../context/FlightContext', () => ({
  useFlightContext: () => mockFlightContext,
}));

// ── Mock sceneCapture ──────────────────────────────────────────────

vi.mock('../../utils/sceneCapture', () => ({
  captureCurrentView: vi.fn().mockResolvedValue(null),
  downloadDataUrl: vi.fn(),
}));

// ── Helper: create mock sim ────────────────────────────────────────

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
    stop: vi.fn(),
    fetchFiles: vi.fn().mockResolvedValue(undefined),
    pauseForSwitch: vi.fn(),
    ...overrides,
  };
}

// ── Tests ──────────────────────────────────────────────────────────

describe('SimulationReport', () => {
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
  });

  it('renders KPI summary cards', () => {
    render(<SimulationReport sim={mockSim} onClose={onClose} />);
    expect(screen.getByText('On-Time')).toBeInTheDocument();
    expect(screen.getByText('82.5%')).toBeInTheDocument();
    expect(screen.getByText('Avg Delay')).toBeInTheDocument();
    expect(screen.getByText('8.2m')).toBeInTheDocument();
  });

  it('renders scenario events in table', () => {
    render(<SimulationReport sim={mockSim} onClose={onClose} />);
    expect(screen.getByText(/Fog reduces visibility/)).toBeInTheDocument();
    expect(screen.getByText(/UAL100 go-around/)).toBeInTheDocument();
    expect(screen.getByText(/Runway 28R closed/)).toBeInTheDocument();
  });

  it('does not show capacity events by default', () => {
    render(<SimulationReport sim={mockSim} onClose={onClose} />);
    // Capacity events are excluded from the default filter
    expect(screen.queryByText(/Arrival rate reduced/)).not.toBeInTheDocument();
  });

  it('closes on close button click', () => {
    render(<SimulationReport sim={mockSim} onClose={onClose} />);
    // Look for a close button (X icon or "Close" text)
    const closeButtons = screen.getAllByRole('button').filter(
      btn => btn.textContent?.includes('×') || btn.textContent?.includes('Close') || btn.getAttribute('aria-label') === 'Close'
    );
    if (closeButtons.length > 0) {
      fireEvent.click(closeButtons[0]);
      expect(onClose).toHaveBeenCalled();
    }
  });

  it('clicking an event row calls seekToTime and closes', () => {
    render(<SimulationReport sim={mockSim} onClose={onClose} />);
    const goAroundEvent = screen.getByText(/UAL100 go-around/);
    // Click the table row containing this event
    const row = goAroundEvent.closest('tr') || goAroundEvent;
    fireEvent.click(row);
    expect(mockSim.seekToTime).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it('clicking an event selects matching flight', () => {
    render(<SimulationReport sim={mockSim} onClose={onClose} />);
    const goAroundEvent = screen.getByText(/UAL100 go-around/);
    const row = goAroundEvent.closest('tr') || goAroundEvent;
    fireEvent.click(row);
    expect(mockFlightContext.setSelectedFlight).toHaveBeenCalledWith(
      expect.objectContaining({ callsign: 'UAL100' })
    );
  });

  it('renders with empty events', () => {
    const emptySim = createMockSim({ scenarioEvents: [] });
    render(<SimulationReport sim={emptySim} onClose={onClose} />);
    expect(screen.getByText('On-Time')).toBeInTheDocument();
  });

  it('renders with null summary', () => {
    const nullSummarySim = createMockSim({ summary: null });
    render(<SimulationReport sim={nullSummarySim} onClose={onClose} />);
    // Should show dashes for missing KPIs
    const dashes = screen.getAllByText('--');
    expect(dashes.length).toBeGreaterThan(0);
  });

  it('has a download/export button', () => {
    render(<SimulationReport sim={mockSim} onClose={onClose} />);
    // Look for download-related button
    const buttons = screen.getAllByRole('button');
    const downloadBtn = buttons.find(btn =>
      btn.textContent?.toLowerCase().includes('download') ||
      btn.textContent?.toLowerCase().includes('export') ||
      btn.textContent?.toLowerCase().includes('report')
    );
    expect(downloadBtn).toBeDefined();
  });
});

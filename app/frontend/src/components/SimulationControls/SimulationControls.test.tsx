import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { SimulationControls } from './SimulationControls';
import type { UseSimulationReplayResult } from '../../hooks/useSimulationReplay';

// ── Mock useSimulationReplay ────────────────────────────────────────

function createMockSim(overrides: Partial<UseSimulationReplayResult> = {}): UseSimulationReplayResult {
  return {
    isActive: false,
    isPlaying: false,
    isLoading: false,
    isFetchingFiles: false,
    switchPaused: false,
    speed: 1 as const,
    currentFrameIndex: 0,
    totalFrames: 0,
    currentSimTime: null,
    flights: [],
    availableFiles: [],
    loadedFile: null,
    summary: null,
    scenarioEvents: [],
    scenarioName: null,
    airport: null,
    simStartTime: null,
    simEndTime: null,
    loadFile: vi.fn().mockResolvedValue(undefined),
    loadDemo: vi.fn().mockResolvedValue(undefined),
    play: vi.fn(),
    pause: vi.fn(),
    togglePlayPause: vi.fn(),
    setSpeed: vi.fn(),
    seekTo: vi.fn(),
    seekToPercent: vi.fn(),
    stop: vi.fn(),
    fetchFiles: vi.fn().mockResolvedValue(undefined),
    pauseForSwitch: vi.fn(),
    ...overrides,
  };
}

let mockSim: UseSimulationReplayResult;

vi.mock('../../hooks/useSimulationReplay', () => ({
  useSimulationReplay: () => mockSim,
}));

let mockFlightContext = {
  dataMode: 'simulation' as 'simulation' | 'live',
  setDataMode: vi.fn(),
  flights: [] as unknown[],
  lastUpdated: null as string | null,
};

vi.mock('../../context/FlightContext', () => ({
  useFlightContext: () => mockFlightContext,
}));

// ── Default props ───────────────────────────────────────────────────

function defaultProps() {
  return {
    onFlightsChange: vi.fn(),
    onActiveChange: vi.fn(),
    onAirportChange: vi.fn().mockResolvedValue(undefined),
    backendReady: true,
    currentAirport: 'KSFO',
    demoReady: false,
    openskyAvailable: true,
  };
}

// ── Tests ───────────────────────────────────────────────────────────

describe('SimulationControls', () => {
  beforeEach(() => {
    mockSim = createMockSim();
    mockFlightContext = {
      dataMode: 'simulation',
      setDataMode: vi.fn(),
      flights: [],
      lastUpdated: null,
    };
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('header button states', () => {
    it('shows "Preparing Simulation..." when backend ready but demo not ready', () => {
      render(<SimulationControls {...defaultProps()} backendReady={true} demoReady={false} />);
      expect(screen.getByText('Preparing Simulation...')).toBeInTheDocument();
    });

    it('shows "Preparing Simulation..." when sim is loading', () => {
      mockSim = createMockSim({ isLoading: true });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);
      expect(screen.getByText('Preparing Simulation...')).toBeInTheDocument();
    });

    it('shows Simulation file picker button in idle state', () => {
      mockSim = createMockSim({ isActive: false, isLoading: false });
      render(
        <SimulationControls {...defaultProps()} demoReady={false} backendReady={false} />
      );
      expect(screen.getByTitle('Load a simulation file')).toBeInTheDocument();
    });

    it('shows playback bar when simulation is active and playing', () => {
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        currentSimTime: '2026-03-22T12:00:00Z',
        speed: 4 as const,
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);
      // Playback bar shows Local Time label and speed buttons (header returns null when playing)
      expect(screen.getByText(/Local Time/)).toBeInTheDocument();
      expect(screen.getAllByText('4x').length).toBeGreaterThanOrEqual(1);
    });

    it('shows "Simulation Paused" header when simulation is paused', () => {
      mockSim = createMockSim({
        isActive: true,
        switchPaused: true,
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);
      // Header shows Simulation Paused, bottom bar also shows Simulation Paused
      const paused = screen.getAllByText('Simulation Paused');
      expect(paused.length).toBeGreaterThanOrEqual(1);
    });

    it('shows playback bar with time when scenario is active', () => {
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        currentSimTime: '2026-03-22T12:00:00Z',
        scenarioName: 'Weather Disruption',
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);
      // Playback bar renders with Local Time label (scenario name shown in file picker, not playback bar)
      expect(screen.getByText(/Local Time/)).toBeInTheDocument();
    });
  });

  describe('auto-start demo', () => {
    it('calls loadDemo when demoReady and currentAirport set', async () => {
      mockSim = createMockSim();
      render(<SimulationControls {...defaultProps()} demoReady={true} currentAirport="KSFO" />);

      await waitFor(() => {
        expect(mockSim.loadDemo).toHaveBeenCalledWith('KSFO');
      });
    });

    it('does not call loadDemo when already active', async () => {
      mockSim = createMockSim({ isActive: true });
      render(<SimulationControls {...defaultProps()} demoReady={true} currentAirport="KSFO" />);

      // Give effects time to run
      await new Promise((r) => setTimeout(r, 50));
      expect(mockSim.loadDemo).not.toHaveBeenCalled();
    });

    it('does not call loadDemo when already loading', async () => {
      mockSim = createMockSim({ isLoading: true });
      render(<SimulationControls {...defaultProps()} demoReady={true} currentAirport="KSFO" />);

      await new Promise((r) => setTimeout(r, 50));
      expect(mockSim.loadDemo).not.toHaveBeenCalled();
    });

    it('does not call loadDemo without currentAirport', async () => {
      mockSim = createMockSim();
      render(<SimulationControls {...defaultProps()} demoReady={true} currentAirport={null} />);

      await new Promise((r) => setTimeout(r, 50));
      expect(mockSim.loadDemo).not.toHaveBeenCalled();
    });
  });

  describe('flight data propagation', () => {
    it('pushes flights to parent when sim active and not paused', () => {
      const flights = [{ icao24: 'abc', callsign: 'UAL1' }] as any;
      mockSim = createMockSim({ isActive: true, switchPaused: false, flights });

      const onFlightsChange = vi.fn();
      const onActiveChange = vi.fn();
      render(
        <SimulationControls
          {...defaultProps()}
          onFlightsChange={onFlightsChange}
          onActiveChange={onActiveChange}
        />
      );

      expect(onFlightsChange).toHaveBeenCalledWith(flights);
      expect(onActiveChange).toHaveBeenCalledWith(true);
    });

    it('pushes null when sim is paused', () => {
      mockSim = createMockSim({ isActive: true, switchPaused: true });

      const onFlightsChange = vi.fn();
      const onActiveChange = vi.fn();
      render(
        <SimulationControls
          {...defaultProps()}
          onFlightsChange={onFlightsChange}
          onActiveChange={onActiveChange}
        />
      );

      expect(onFlightsChange).toHaveBeenCalledWith(null);
      expect(onActiveChange).toHaveBeenCalledWith(false);
    });

    it('pushes null when sim is inactive', () => {
      mockSim = createMockSim({ isActive: false });

      const onFlightsChange = vi.fn();
      render(
        <SimulationControls
          {...defaultProps()}
          onFlightsChange={onFlightsChange}
          backendReady={false}
          demoReady={false}
        />
      );

      expect(onFlightsChange).toHaveBeenCalledWith(null);
    });
  });

  describe('playback bar', () => {
    it('renders PlaybackBar when sim is active and not paused', () => {
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        switchPaused: false,
        totalFrames: 100,
        currentFrameIndex: 50,
        currentSimTime: '2026-03-22T12:00:00Z',
        flights: [{ icao24: 'a' }] as any,
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      expect(screen.getByText('Mar 22')).toBeInTheDocument();
      expect(screen.getByText('Exit')).toBeInTheDocument();
      // Speed buttons render in the playback bar (also "1x" appears in header badge)
      expect(screen.getAllByText('1x').length).toBeGreaterThanOrEqual(1);
      // Flight count in playback bar
      expect(screen.getByText('flights')).toBeInTheDocument();
    });

    it('does not render PlaybackBar when paused', () => {
      mockSim = createMockSim({ isActive: true, switchPaused: true });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      expect(screen.queryByText('flights')).not.toBeInTheDocument();
    });

    it('renders speed buttons', () => {
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        totalFrames: 100,
        currentSimTime: '2026-03-22T12:00:00Z',
        flights: [],
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      // Sub-1x speeds use fraction labels, others use Nx format
      expect(screen.getByText('¼x')).toBeInTheDocument();
      expect(screen.getByText('½x')).toBeInTheDocument();
      expect(screen.getByText('2x')).toBeInTheDocument();
      expect(screen.getByText('4x')).toBeInTheDocument();
      expect(screen.getByText('10x')).toBeInTheDocument();
      expect(screen.getByText('30x')).toBeInTheDocument();
      expect(screen.getByText('60x')).toBeInTheDocument();
    });

    it('calls setSpeed when speed button clicked', () => {
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        totalFrames: 100,
        currentSimTime: '2026-03-22T12:00:00Z',
        flights: [],
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      fireEvent.click(screen.getByText('30x'));
      expect(mockSim.setSpeed).toHaveBeenCalledWith(30);
    });

    it('calls togglePlayPause when play/pause button clicked', () => {
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        totalFrames: 100,
        currentSimTime: '2026-03-22T12:00:00Z',
        flights: [],
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      fireEvent.click(screen.getByTitle('Pause'));
      expect(mockSim.togglePlayPause).toHaveBeenCalled();
    });

    it('calls stop when Exit button clicked', () => {
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        totalFrames: 100,
        currentSimTime: '2026-03-22T12:00:00Z',
        flights: [],
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      fireEvent.click(screen.getByText('Exit'));
      expect(mockSim.stop).toHaveBeenCalled();
    });
  });

  describe('PausedBar', () => {
    it('renders when simulation is paused for switch', () => {
      mockSim = createMockSim({
        isActive: true,
        switchPaused: true,
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      // "Simulation Paused" appears in both header badge and bottom bar
      const paused = screen.getAllByText('Simulation Paused');
      expect(paused.length).toBeGreaterThanOrEqual(1);
    });

    it('calls stop when Exit clicked in paused bar', () => {
      mockSim = createMockSim({
        isActive: true,
        switchPaused: true,
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      fireEvent.click(screen.getByText('Exit'));
      expect(mockSim.stop).toHaveBeenCalled();
    });
  });

  describe('restart after exit', () => {
    it('shows Start Simulation button after demo was auto-started then stopped', async () => {
      // Start with demo auto-starting
      mockSim = createMockSim();
      const { rerender } = render(
        <SimulationControls {...defaultProps()} demoReady={true} currentAirport="KSFO" />
      );

      // Demo was auto-started (loadDemo called)
      await waitFor(() => {
        expect(mockSim.loadDemo).toHaveBeenCalledWith('KSFO');
      });

      // Now sim is stopped (user clicked Exit) — sim becomes inactive
      mockSim = createMockSim({ isActive: false, isLoading: false });
      rerender(
        <SimulationControls {...defaultProps()} demoReady={true} currentAirport="KSFO" />
      );

      expect(screen.getByText('Start Simulation')).toBeInTheDocument();
    });

    it('calls loadDemo when Start Simulation clicked', async () => {
      mockSim = createMockSim();
      const { rerender } = render(
        <SimulationControls {...defaultProps()} demoReady={true} currentAirport="KSFO" />
      );

      await waitFor(() => {
        expect(mockSim.loadDemo).toHaveBeenCalled();
      });

      // Sim stopped
      mockSim = createMockSim({ isActive: false, isLoading: false });
      rerender(
        <SimulationControls {...defaultProps()} demoReady={true} currentAirport="KSFO" />
      );

      fireEvent.click(screen.getByText('Start Simulation'));
      expect(mockSim.loadDemo).toHaveBeenCalledWith('KSFO');
    });
  });

  describe('file picker', () => {
    it('opens file picker when Simulation button clicked', () => {
      mockSim = createMockSim();
      render(<SimulationControls {...defaultProps()} backendReady={false} demoReady={false} />);

      fireEvent.click(screen.getByTitle('Load a simulation file'));
      expect(screen.getByText('Load Simulation')).toBeInTheDocument();
    });

    it('closes file picker on close button', () => {
      mockSim = createMockSim();
      render(<SimulationControls {...defaultProps()} backendReady={false} demoReady={false} />);

      fireEvent.click(screen.getByTitle('Load a simulation file'));
      expect(screen.getByText('Load Simulation')).toBeInTheDocument();

      fireEvent.click(screen.getByText('\u00d7'));
      expect(screen.queryByText('Load Simulation')).not.toBeInTheDocument();
    });

    it('renders file list and calls loadFile on click', () => {
      mockSim = createMockSim({
        availableFiles: [
          {
            filename: 'sim_sfo.json',
            airport: 'SFO',
            total_flights: 100,
            arrivals: 50,
            departures: 50,
            duration_hours: 24,
            size_kb: 500,
          },
        ],
      });
      render(<SimulationControls {...defaultProps()} backendReady={false} demoReady={false} />);

      fireEvent.click(screen.getByTitle('Load a simulation file'));
      expect(screen.getByText('Load Simulation')).toBeInTheDocument();

      fireEvent.click(screen.getByTitle('sim_sfo.json'));
      expect(mockSim.loadFile).toHaveBeenCalledWith('sim_sfo.json', 0, 24);
    });
  });

  describe('fetches files on mount', () => {
    it('calls fetchFiles on mount', () => {
      mockSim = createMockSim();
      render(<SimulationControls {...defaultProps()} backendReady={false} demoReady={false} />);
      expect(mockSim.fetchFiles).toHaveBeenCalled();
    });
  });

  describe('event markers in playback bar', () => {
    it('renders event legend when scenario events exist', () => {
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        totalFrames: 100,
        currentSimTime: '2026-03-22T12:00:00Z',
        flights: [],
        scenarioEvents: [
          { time: '2026-03-22T06:00:00Z', event_type: 'weather', description: 'Fog' },
          { time: '2026-03-22T10:00:00Z', event_type: 'runway', description: 'Closed' },
        ],
        simStartTime: '2026-03-22T00:00:00Z',
        simEndTime: '2026-03-22T23:59:00Z',
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      expect(screen.getByText('Weather')).toBeInTheDocument();
      expect(screen.getByText('Runway')).toBeInTheDocument();
    });

    it('filters out capacity events from legend', () => {
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        totalFrames: 100,
        currentSimTime: '2026-03-22T12:00:00Z',
        flights: [],
        scenarioEvents: [
          { time: '2026-03-22T06:00:00Z', event_type: 'capacity', description: 'Reduced' },
        ],
        simStartTime: '2026-03-22T00:00:00Z',
        simEndTime: '2026-03-22T23:59:00Z',
      });
      render(<SimulationControls {...defaultProps()} demoReady={true} />);

      expect(screen.queryByText('Capacity')).not.toBeInTheDocument();
    });
  });

  describe('data mode toggle', () => {
    /** Helper to find the toggle button (in the rounded-md toggle group). */
    function getToggleButton(label: string): HTMLElement {
      const buttons = screen.getAllByText(label).filter(
        el => el.tagName === 'BUTTON' && el.className.includes('rounded-md')
      );
      return buttons[0];
    }

    it('renders the Simulation/Live toggle', () => {
      render(<SimulationControls {...defaultProps()} />);

      expect(getToggleButton('Simulation')).toBeInTheDocument();
      expect(getToggleButton('Live')).toBeInTheDocument();
    });

    it('Simulation button is active by default', () => {
      render(<SimulationControls {...defaultProps()} />);

      const simButton = getToggleButton('Simulation');
      expect(simButton.className).toContain('bg-indigo-600');
    });

    it('clicking Live calls setDataMode with live', () => {
      render(<SimulationControls {...defaultProps()} />);

      fireEvent.click(getToggleButton('Live'));
      expect(mockFlightContext.setDataMode).toHaveBeenCalledWith('live');
    });

    it('clicking Simulation calls setDataMode with simulation', () => {
      mockFlightContext.dataMode = 'live';
      render(<SimulationControls {...defaultProps()} />);

      fireEvent.click(getToggleButton('Simulation'));
      expect(mockFlightContext.setDataMode).toHaveBeenCalledWith('simulation');
    });

    it('hides simulation file picker button in live mode', () => {
      mockFlightContext.dataMode = 'live';
      render(<SimulationControls {...defaultProps()} />);

      expect(screen.queryByTitle('Load a simulation file')).not.toBeInTheDocument();
    });

    it('hides playback bar in live mode even when sim is active', () => {
      mockFlightContext.dataMode = 'live';
      mockSim = createMockSim({
        isActive: true,
        isPlaying: true,
        totalFrames: 100,
        currentSimTime: '2026-03-22T12:00:00Z',
      });
      render(<SimulationControls {...defaultProps()} />);

      // Playback bar has Play/Pause button — should not be present
      expect(screen.queryByTitle('Pause')).not.toBeInTheDocument();
    });

    it('shows Live bar with flight count in live mode', () => {
      mockFlightContext.dataMode = 'live';
      mockFlightContext.flights = [{ icao24: 'a' }, { icao24: 'b' }, { icao24: 'c' }];
      mockFlightContext.lastUpdated = '2026-04-02T10:00:00Z';
      render(<SimulationControls {...defaultProps()} />);

      expect(screen.getByText('3')).toBeInTheDocument();
      expect(screen.getByText('aircraft')).toBeInTheDocument();
      expect(screen.getByText('OpenSky ADS-B')).toBeInTheDocument();
    });

    it('shows Live indicator with pulsing dot', () => {
      mockFlightContext.dataMode = 'live';
      render(<SimulationControls {...defaultProps()} />);

      // "Live" label in the bar (uppercase)
      const liveLabels = screen.getAllByText('Live');
      // At least one should be in the LiveBar (has LIVE class styling)
      expect(liveLabels.length).toBeGreaterThanOrEqual(1);
    });

    it('Live toggle button is active in live mode', () => {
      mockFlightContext.dataMode = 'live';
      render(<SimulationControls {...defaultProps()} />);

      const liveButtons = screen.getAllByText('Live');
      // Find the toggle button (in the DataModeToggle)
      const toggleButton = liveButtons.find(el => el.tagName === 'BUTTON' && el.className.includes('bg-emerald'));
      expect(toggleButton).toBeTruthy();
    });

    it('stops active simulation when switching to live', () => {
      mockSim = createMockSim({ isActive: true, isPlaying: true });
      render(<SimulationControls {...defaultProps()} />);

      fireEvent.click(getToggleButton('Live'));

      expect(mockSim.stop).toHaveBeenCalled();
      expect(mockFlightContext.setDataMode).toHaveBeenCalledWith('live');
    });

    it('does not stop simulation when switching to sim (already sim)', () => {
      mockSim = createMockSim({ isActive: false });
      render(<SimulationControls {...defaultProps()} />);

      fireEvent.click(getToggleButton('Simulation'));

      expect(mockSim.stop).not.toHaveBeenCalled();
    });
  });
});

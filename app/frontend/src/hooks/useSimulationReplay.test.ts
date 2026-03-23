import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useSimulationReplay } from './useSimulationReplay';

// ── Test fixtures ───────────────────────────────────────────────────

function makeDemoData(frameCount = 3) {
  // Timestamps 30 seconds apart (matching real simulation snapshot interval)
  const base = new Date('2026-03-22T00:00:00Z');
  const timestamps = Array.from({ length: frameCount }, (_, i) => {
    const d = new Date(base.getTime() + i * 30 * 1000);
    return d.toISOString().replace('.000Z', 'Z');
  });
  const frames: Record<string, Array<Record<string, unknown>>> = {};
  timestamps.forEach((ts, i) => {
    frames[ts] = [
      {
        time: ts,
        icao24: `abc${i}`,
        callsign: `UAL${i}`,
        latitude: 37.62,
        longitude: -122.38,
        altitude: 1000 * i,
        velocity: 120,
        heading: 90,
        phase: 'approaching',
        on_ground: false,
        aircraft_type: 'A320',
      },
    ];
  });
  return {
    config: { airport: 'SFO' },
    summary: { scenario_name: 'Test scenario' },
    schedule: [],
    frames,
    frame_timestamps: timestamps,
    frame_count: frameCount,
    phase_transitions: [],
    gate_events: [],
    scenario_events: [],
  };
}

function mockFetchSuccess(data: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status >= 200 && status < 300,
    status,
    statusText: 'OK',
    json: () => Promise.resolve(data),
  });
}

// ── Tests ───────────────────────────────────────────────────────────

describe('useSimulationReplay', () => {
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.useRealTimers();
    vi.restoreAllMocks();
    delete window.__simControl;
  });

  describe('initial state', () => {
    it('starts inactive with no flights', () => {
      globalThis.fetch = mockFetchSuccess({ files: [] });
      const { result } = renderHook(() => useSimulationReplay());
      expect(result.current.isActive).toBe(false);
      expect(result.current.isPlaying).toBe(false);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.switchPaused).toBe(false);
      expect(result.current.flights).toEqual([]);
      expect(result.current.totalFrames).toBe(0);
      expect(result.current.currentSimTime).toBeNull();
      expect(result.current.speed).toBe(1);
    });
  });

  describe('fetchFiles', () => {
    it('fetches simulation file list', async () => {
      const files = [
        { filename: 'sim1.json', airport: 'SFO', total_flights: 50, arrivals: 25, departures: 25, duration_hours: 24, size_kb: 100 },
      ];
      globalThis.fetch = mockFetchSuccess({ files });
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.fetchFiles();
      });

      expect(result.current.availableFiles).toEqual(files);
      expect(result.current.isFetchingFiles).toBe(false);
    });

    it('handles fetch failure gracefully', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network error'));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.fetchFiles();
      });

      expect(result.current.availableFiles).toEqual([]);
      expect(result.current.isFetchingFiles).toBe(false);
    });
  });

  describe('loadDemo', () => {
    it('loads demo data and auto-plays', async () => {
      const demoData = makeDemoData(3);
      globalThis.fetch = mockFetchSuccess(demoData);

      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadDemo('KSFO');
      });

      expect(globalThis.fetch).toHaveBeenCalledWith('/api/simulation/demo/KSFO');
      expect(result.current.isActive).toBe(true);
      expect(result.current.isPlaying).toBe(true);
      expect(result.current.isLoading).toBe(false);
      expect(result.current.loadedFile).toBe('demo_KSFO');
      expect(result.current.totalFrames).toBe(3);
      expect(result.current.flights.length).toBe(1);
      expect(result.current.flights[0].icao24).toBe('abc0');
      expect(result.current.flights[0].data_source).toBe('simulation');
    });

    it('handles 202 (still generating) without crashing', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 202,
        statusText: 'Accepted',
        json: () => Promise.resolve({}),
      });
      const consoleSpy = vi.spyOn(console, 'log').mockImplementation(() => {});

      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadDemo('KSFO');
      });

      expect(result.current.isActive).toBe(false);
      expect(result.current.isLoading).toBe(false);
      consoleSpy.mockRestore();
    });

    it('handles fetch failure gracefully', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network error'));
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadDemo('KSFO');
      });

      expect(result.current.isActive).toBe(false);
      expect(result.current.isLoading).toBe(false);
      consoleSpy.mockRestore();
    });

    it('clears switchPaused when loading new demo', async () => {
      const demoData = makeDemoData(3);
      globalThis.fetch = mockFetchSuccess(demoData);

      const { result } = renderHook(() => useSimulationReplay());

      // Load first demo
      await act(async () => {
        await result.current.loadDemo('KSFO');
      });

      // Pause for switch
      act(() => {
        result.current.pauseForSwitch();
      });
      expect(result.current.switchPaused).toBe(true);

      // Load new demo — should clear switchPaused
      await act(async () => {
        await result.current.loadDemo('EGLL');
      });
      expect(result.current.switchPaused).toBe(false);
      expect(result.current.isPlaying).toBe(true);
    });
  });

  describe('loadFile', () => {
    it('loads a simulation file with time range', async () => {
      const simData = makeDemoData(5);
      globalThis.fetch = mockFetchSuccess(simData);

      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('sim_sfo.json', 6, 18);
      });

      expect(globalThis.fetch).toHaveBeenCalledWith(
        '/api/simulation/data/sim_sfo.json?start_hour=6&end_hour=18'
      );
      expect(result.current.isActive).toBe(true);
      expect(result.current.isPlaying).toBe(false);
      expect(result.current.loadedFile).toBe('sim_sfo.json');
    });

    it('handles load failure', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      });
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {});

      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('bad.json');
      });

      expect(result.current.isActive).toBe(false);
      expect(result.current.isLoading).toBe(false);
      consoleSpy.mockRestore();
    });
  });

  describe('pauseForSwitch', () => {
    it('pauses playback and sets switchPaused flag', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(3));

      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadDemo('KSFO');
      });
      expect(result.current.isPlaying).toBe(true);
      expect(result.current.switchPaused).toBe(false);

      act(() => {
        result.current.pauseForSwitch();
      });

      expect(result.current.isPlaying).toBe(false);
      expect(result.current.switchPaused).toBe(true);
      expect(result.current.isActive).toBe(true); // still has data
    });
  });

  describe('playback controls', () => {
    it('play/pause/togglePlayPause work correctly', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(10));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });
      expect(result.current.isPlaying).toBe(false);

      act(() => result.current.play());
      expect(result.current.isPlaying).toBe(true);

      act(() => result.current.pause());
      expect(result.current.isPlaying).toBe(false);

      act(() => result.current.togglePlayPause());
      expect(result.current.isPlaying).toBe(true);

      act(() => result.current.togglePlayPause());
      expect(result.current.isPlaying).toBe(false);
    });

    it('play does nothing when no data loaded', () => {
      globalThis.fetch = mockFetchSuccess({ files: [] });
      const { result } = renderHook(() => useSimulationReplay());

      act(() => result.current.play());
      expect(result.current.isPlaying).toBe(false);
    });

    it('setSpeed changes playback speed', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(5));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      act(() => result.current.setSpeed(30));
      expect(result.current.speed).toBe(30);

      act(() => result.current.setSpeed(60));
      expect(result.current.speed).toBe(60);
    });

    it('seekTo clamps to valid frame range', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(5));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      act(() => result.current.seekTo(3));
      expect(result.current.currentFrameIndex).toBe(3);

      act(() => result.current.seekTo(-5));
      expect(result.current.currentFrameIndex).toBe(0);

      act(() => result.current.seekTo(999));
      expect(result.current.currentFrameIndex).toBe(4); // clamped to totalFrames - 1
    });

    it('seekToPercent maps percentage to frame index', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(5));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      act(() => result.current.seekToPercent(50));
      expect(result.current.currentFrameIndex).toBe(2);

      act(() => result.current.seekToPercent(100));
      expect(result.current.currentFrameIndex).toBe(4);

      act(() => result.current.seekToPercent(0));
      expect(result.current.currentFrameIndex).toBe(0);
    });

    it('seekToPercent does nothing with no frames', () => {
      globalThis.fetch = mockFetchSuccess({ files: [] });
      const { result } = renderHook(() => useSimulationReplay());

      act(() => result.current.seekToPercent(50));
      expect(result.current.currentFrameIndex).toBe(0);
    });

    it('play restarts from beginning when at last frame', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(3));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      // Seek to last frame
      act(() => result.current.seekTo(2));
      expect(result.current.currentFrameIndex).toBe(2);

      // Play should restart from 0
      act(() => result.current.play());
      expect(result.current.currentFrameIndex).toBe(0);
      expect(result.current.isPlaying).toBe(true);
    });
  });

  describe('stop', () => {
    it('resets all state', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(3));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadDemo('KSFO');
      });
      expect(result.current.isActive).toBe(true);
      act(() => result.current.stop());

      expect(result.current.isActive).toBe(false);
      expect(result.current.isPlaying).toBe(false);
      expect(result.current.switchPaused).toBe(false);
      expect(result.current.flights).toEqual([]);
      expect(result.current.loadedFile).toBeNull();
      expect(result.current.currentFrameIndex).toBe(0);
    });
  });

  describe('frame advancement', () => {
    it('advances frames during playback', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(5));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      act(() => result.current.play());
      expect(result.current.currentFrameIndex).toBe(0);

      // Advance time to trigger interval (1000ms at 1x speed)
      await act(async () => {
        vi.advanceTimersByTime(1100);
      });

      expect(result.current.currentFrameIndex).toBeGreaterThan(0);
    });

    it('stops playing at the last frame', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(2));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      act(() => result.current.play());

      // Advance past all frames
      await act(async () => {
        vi.advanceTimersByTime(5000);
      });

      expect(result.current.isPlaying).toBe(false);
      // Should stop at last valid frame
      expect(result.current.currentFrameIndex).toBeLessThanOrEqual(1);
    });
  });

  describe('currentSimTime', () => {
    it('returns timestamp for current frame', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(3));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      expect(result.current.currentSimTime).toBe('2026-03-22T00:00:00Z');

      act(() => result.current.seekTo(1));
      expect(result.current.currentSimTime).toBe('2026-03-22T00:00:30Z');
    });
  });

  describe('derived fields', () => {
    it('exposes airport from config', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(3));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadDemo('KSFO');
      });

      expect(result.current.airport).toBe('SFO');
    });

    it('exposes scenarioName from summary', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(3));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadDemo('KSFO');
      });

      expect(result.current.scenarioName).toBe('Test scenario');
    });

    it('exposes simStartTime and simEndTime', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(3));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      expect(result.current.simStartTime).toBe('2026-03-22T00:00:00Z');
      expect(result.current.simEndTime).toBe('2026-03-22T00:01:00Z');
    });
  });

  describe('snapshotToFlight mapping', () => {
    it('maps simulation phases to flight phases correctly', async () => {
      const data = makeDemoData(1);
      // Override the snapshot phase
      const ts = data.frame_timestamps[0];
      (data.frames[ts][0] as Record<string, unknown>).phase = 'taxi_to_gate';

      globalThis.fetch = mockFetchSuccess(data);
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      expect(result.current.flights[0].flight_phase).toBe('taxi_in');
    });

    it('defaults unknown phase to parked', async () => {
      const data = makeDemoData(1);
      const ts = data.frame_timestamps[0];
      (data.frames[ts][0] as Record<string, unknown>).phase = 'unknown_phase';

      globalThis.fetch = mockFetchSuccess(data);
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      expect(result.current.flights[0].flight_phase).toBe('parked');
    });
  });

  describe('window.__simControl', () => {
    it('exposes control API on window', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(3));
      const { result } = renderHook(() => useSimulationReplay());

      await act(async () => {
        await result.current.loadFile('test.json');
      });

      expect(window.__simControl).toBeDefined();
      expect(window.__simControl!.getInfo().totalFrames).toBe(3);
      expect(window.__simControl!.getInfo().isActive).toBe(true);
    });

    it('cleans up window API on unmount', async () => {
      globalThis.fetch = mockFetchSuccess(makeDemoData(1));
      const { unmount } = renderHook(() => useSimulationReplay());

      expect(window.__simControl).toBeDefined();

      unmount();
      expect(window.__simControl).toBeUndefined();
    });
  });
});

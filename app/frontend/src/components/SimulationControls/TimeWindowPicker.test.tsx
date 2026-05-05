import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TimeWindowPicker } from './TimeWindowPicker';
import type { SimulationMetadata } from '../../hooks/useSimulationReplay';

function createMockMetadata(overrides: Partial<SimulationMetadata> = {}): SimulationMetadata {
  return {
    days: ['2026-03-15'],
    total_frames: 1000,
    total_snapshots: 50000,
    estimated_frames_per_hour: 120,
    duration_hours: 8,
    config: { airport: 'SFO' },
    summary: { total_flights: 60 },
    ...overrides,
  };
}

describe('TimeWindowPicker', () => {
  const defaultProps = {
    metadata: createMockMetadata(),
    filename: 'sim_2026-03-15.json',
    isLoading: false,
    onLoad: vi.fn(),
    onBack: vi.fn(),
  };

  it('renders airport name, duration, and frame count from metadata', () => {
    render(<TimeWindowPicker {...defaultProps} />);

    expect(screen.getByText('SFO')).toBeInTheDocument();
    expect(screen.getByText(/8h/)).toBeInTheDocument();
    expect(screen.getByText(/1000 frames/)).toBeInTheDocument();
  });

  it('renders total flights from summary', () => {
    render(<TimeWindowPicker {...defaultProps} />);

    expect(screen.getByText(/60 flights/)).toBeInTheDocument();
  });

  it('does not show day selector when only one day', () => {
    render(<TimeWindowPicker {...defaultProps} />);

    expect(screen.queryByText('Day')).not.toBeInTheDocument();
  });

  it('shows day selector buttons when days.length > 1', () => {
    const metadata = createMockMetadata({ days: ['2026-03-15', '2026-03-16', '2026-03-17'] });
    render(<TimeWindowPicker {...defaultProps} metadata={metadata} />);

    expect(screen.getByText('Day')).toBeInTheDocument();
    expect(screen.getByText('Mar 15')).toBeInTheDocument();
    expect(screen.getByText('Mar 16')).toBeInTheDocument();
    expect(screen.getByText('Mar 17')).toBeInTheDocument();
  });

  describe('quick preset buttons', () => {
    it('renders Morning, Afternoon, Evening, Full Day buttons', () => {
      render(<TimeWindowPicker {...defaultProps} />);

      expect(screen.getByText('Morning')).toBeInTheDocument();
      expect(screen.getByText('Afternoon')).toBeInTheDocument();
      expect(screen.getByText('Evening')).toBeInTheDocument();
      expect(screen.getByText('Full Day')).toBeInTheDocument();
    });

    it('Morning preset sets time range to 6:00 AM - 12:00 PM', () => {
      render(<TimeWindowPicker {...defaultProps} />);

      fireEvent.click(screen.getByText('Morning'));

      expect(screen.getByText('6:00 AM')).toBeInTheDocument();
      expect(screen.getByText('12:00 PM')).toBeInTheDocument();
    });

    it('Afternoon preset sets time range to 12:00 PM - 6:00 PM', () => {
      render(<TimeWindowPicker {...defaultProps} />);

      fireEvent.click(screen.getByText('Afternoon'));

      expect(screen.getByText('12:00 PM')).toBeInTheDocument();
      expect(screen.getByText('6:00 PM')).toBeInTheDocument();
    });

    it('Evening preset sets time range to 6:00 PM - 12:00 PM (hour 24)', () => {
      render(<TimeWindowPicker {...defaultProps} />);

      fireEvent.click(screen.getByText('Evening'));

      expect(screen.getByText('6:00 PM')).toBeInTheDocument();
      // Hour 24 formats as 12:00 PM per the formatHour logic
      expect(screen.getByText('12:00 PM')).toBeInTheDocument();
    });

    it('Full Day preset sets time range to 12:00 AM - 12:00 PM (0-24h)', () => {
      render(<TimeWindowPicker {...defaultProps} />);

      fireEvent.click(screen.getByText('Full Day'));

      // Start=0 formats as 12:00 AM, end=24 formats as 12:00 PM
      expect(screen.getByText('12:00 AM')).toBeInTheDocument();
      expect(screen.getByText('12:00 PM')).toBeInTheDocument();
    });
  });

  describe('Load button', () => {
    it('calls onLoad with filename, startISO, and endISO when clicked', () => {
      const onLoad = vi.fn();
      render(<TimeWindowPicker {...defaultProps} onLoad={onLoad} />);

      // Default: startHour=0, endHour=6 (DEFAULT_WINDOW_HOURS)
      fireEvent.click(screen.getByRole('button', { name: /Load/ }));

      expect(onLoad).toHaveBeenCalledTimes(1);
      expect(onLoad).toHaveBeenCalledWith(
        'sim_2026-03-15.json',
        '2026-03-15T00:00:00.000Z',
        '2026-03-15T06:00:00.000Z'
      );
    });

    it('calls onLoad with updated times after selecting a preset', () => {
      const onLoad = vi.fn();
      render(<TimeWindowPicker {...defaultProps} onLoad={onLoad} />);

      fireEvent.click(screen.getByText('Morning'));
      fireEvent.click(screen.getByRole('button', { name: /Load/ }));

      expect(onLoad).toHaveBeenCalledWith(
        'sim_2026-03-15.json',
        '2026-03-15T06:00:00.000Z',
        '2026-03-15T12:00:00.000Z'
      );
    });

    it('shows spinner when isLoading is true', () => {
      render(<TimeWindowPicker {...defaultProps} isLoading={true} />);

      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('is disabled when isLoading is true', () => {
      render(<TimeWindowPicker {...defaultProps} isLoading={true} />);

      const loadButton = screen.getByRole('button', { name: /Loading/ });
      expect(loadButton).toBeDisabled();
    });

    it('shows "Load Summary & Events" text in batch mode', () => {
      const metadata = createMockMetadata({ total_frames: 0 });
      render(<TimeWindowPicker {...defaultProps} metadata={metadata} />);

      expect(screen.getByText('Load Summary & Events')).toBeInTheDocument();
    });
  });

  describe('Back button', () => {
    it('calls onBack when close (x) button is clicked', () => {
      const onBack = vi.fn();
      render(<TimeWindowPicker {...defaultProps} onBack={onBack} />);

      // The × button
      const closeButton = screen.getByText('×');
      fireEvent.click(closeButton);

      expect(onBack).toHaveBeenCalledTimes(1);
    });

    it('calls onBack when back arrow button is clicked', () => {
      const onBack = vi.fn();
      render(<TimeWindowPicker {...defaultProps} onBack={onBack} />);

      const backButton = screen.getByTitle('Back to file list');
      fireEvent.click(backButton);

      expect(onBack).toHaveBeenCalledTimes(1);
    });
  });

  describe('batch mode', () => {
    it('shows batch mode warning when total_frames === 0 and total_flights > 0', () => {
      const metadata = createMockMetadata({ total_frames: 0 });
      render(<TimeWindowPicker {...defaultProps} metadata={metadata} />);

      expect(screen.getByText('Batch mode simulation')).toBeInTheDocument();
      expect(screen.getByText(/this file was run without position recording/)).toBeInTheDocument();
    });

    it('shows "batch mode" in the info line', () => {
      const metadata = createMockMetadata({ total_frames: 0 });
      render(<TimeWindowPicker {...defaultProps} metadata={metadata} />);

      expect(screen.getByText('batch mode')).toBeInTheDocument();
    });

    it('does not show batch mode warning when total_frames > 0', () => {
      render(<TimeWindowPicker {...defaultProps} />);

      expect(screen.queryByText('Batch mode simulation')).not.toBeInTheDocument();
    });

    it('does not show quick presets in batch mode', () => {
      const metadata = createMockMetadata({ total_frames: 0 });
      render(<TimeWindowPicker {...defaultProps} metadata={metadata} />);

      expect(screen.queryByText('Morning')).not.toBeInTheDocument();
      expect(screen.queryByText('Afternoon')).not.toBeInTheDocument();
    });
  });

  describe('estimated load', () => {
    it('shows estimated frames for the selected window', () => {
      render(<TimeWindowPicker {...defaultProps} />);

      // Default window is 6h, estimated_frames_per_hour = 120, so 720 frames
      expect(screen.getByText(/720 frames/)).toBeInTheDocument();
    });

    it('does not show estimated load section in batch mode', () => {
      const metadata = createMockMetadata({ total_frames: 0 });
      render(<TimeWindowPicker {...defaultProps} metadata={metadata} />);

      expect(screen.queryByText('Estimated load')).not.toBeInTheDocument();
    });
  });
});

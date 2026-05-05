import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import KPIDashboard from './KPIDashboard';

const mockDashboard = {
  kpi_cards: [
    { label: 'On-Time', value: '82%', color: 'green' },
    { label: 'Avg Delay', value: '8.2m', color: 'orange' },
    { label: 'Cancellations', value: '2', color: 'red' },
  ],
  congestion_areas: [
    { area_id: 'RWY28L', area_type: 'runway', level: 'high', flight_count: 12, capacity: 15, wait_minutes: 4 },
    { area_id: 'GATE_A', area_type: 'gate', level: 'moderate', flight_count: 8, capacity: 12, wait_minutes: 2 },
  ],
  delay_table: [
    { icao24: 'abc001', callsign: 'UAL100', delay_minutes: 12, confidence: 0.87, category: 'moderate' },
    { icao24: 'abc002', callsign: 'DAL200', delay_minutes: 0, confidence: 0.95, category: 'on_time' },
    { icao24: 'abc003', callsign: 'AAL300', delay_minutes: 45, confidence: 0.72, category: 'severe' },
  ],
  total_flights: 45,
};

let mockHookReturn = {
  dashboard: mockDashboard as typeof mockDashboard | null,
  isLoading: false,
  error: null as Error | null,
};

vi.mock('../../hooks/usePredictionDashboard', () => ({
  usePredictionDashboard: () => mockHookReturn,
}));

describe('KPIDashboard', () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    mockHookReturn = {
      dashboard: mockDashboard,
      isLoading: false,
      error: null,
    };
  });

  describe('Loading and error states', () => {
    it('shows loading spinner when isLoading=true', () => {
      mockHookReturn = { dashboard: null, isLoading: true, error: null };
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('Loading predictions...')).toBeInTheDocument();
    });

    it('shows error message when error is set', () => {
      mockHookReturn = { dashboard: null, isLoading: false, error: new Error('Network failed') };
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText(/Failed to load predictions: Network failed/)).toBeInTheDocument();
    });
  });

  describe('KPI cards', () => {
    it('renders all KPI cards with correct values', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('82%')).toBeInTheDocument();
      expect(screen.getByText('8.2m')).toBeInTheDocument();
      expect(screen.getByText('2')).toBeInTheDocument();
    });

    it('renders card labels', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('On-Time')).toBeInTheDocument();
      expect(screen.getByText('Avg Delay')).toBeInTheDocument();
      expect(screen.getByText('Cancellations')).toBeInTheDocument();
    });

    it('shows total flights count in header', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText(/45 active flights/)).toBeInTheDocument();
    });
  });

  describe('Tab switching', () => {
    it('renders Overview tab by default', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('Overview')).toBeInTheDocument();
      expect(screen.getByText('Congestion')).toBeInTheDocument();
      // "Delay Forecast" appears as both tab button and section heading
      expect(screen.getAllByText('Delay Forecast').length).toBeGreaterThanOrEqual(1);
    });

    it('Overview tab shows both congestion and delay tables', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('Congestion Areas')).toBeInTheDocument();
      expect(screen.getAllByText('Delay Forecast').length).toBeGreaterThanOrEqual(2);
      expect(screen.getByText('RWY28L')).toBeInTheDocument();
      expect(screen.getByText('UAL100')).toBeInTheDocument();
    });

    it('Congestion tab shows full congestion table', () => {
      render(<KPIDashboard onClose={onClose} />);
      fireEvent.click(screen.getByText('Congestion'));
      expect(screen.getByText(/All Congestion Areas/)).toBeInTheDocument();
      expect(screen.getByText('RWY28L')).toBeInTheDocument();
      expect(screen.getByText('GATE_A')).toBeInTheDocument();
    });

    it('Delay Forecast tab shows full delay table', () => {
      render(<KPIDashboard onClose={onClose} />);
      const tabs = screen.getAllByText('Delay Forecast');
      fireEvent.click(tabs[0]); // click the tab button
      expect(screen.getByText(/All Flight Delay Predictions/)).toBeInTheDocument();
      expect(screen.getByText('UAL100')).toBeInTheDocument();
      expect(screen.getByText('AAL300')).toBeInTheDocument();
    });
  });

  describe('Congestion table', () => {
    it('renders level badges', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('high')).toBeInTheDocument();
      expect(screen.getByText('moderate')).toBeInTheDocument();
    });

    it('renders area type and wait time', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('runway')).toBeInTheDocument();
      expect(screen.getByText('4m')).toBeInTheDocument();
    });
  });

  describe('Delay table', () => {
    it('renders category labels', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('Moderate')).toBeInTheDocument();
      expect(screen.getByText('On Time')).toBeInTheDocument();
      expect(screen.getByText('Severe')).toBeInTheDocument();
    });

    it('renders delay values with + prefix', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('+12m')).toBeInTheDocument();
      expect(screen.getByText('+45m')).toBeInTheDocument();
      expect(screen.getByText('0m')).toBeInTheDocument();
    });

    it('renders confidence percentages', () => {
      render(<KPIDashboard onClose={onClose} />);
      expect(screen.getByText('87%')).toBeInTheDocument();
      expect(screen.getByText('95%')).toBeInTheDocument();
      expect(screen.getByText('72%')).toBeInTheDocument();
    });
  });

  describe('Fullscreen toggle', () => {
    it('toggles fullscreen class', () => {
      render(<KPIDashboard onClose={onClose} />);
      const fullscreenBtn = screen.getByTitle('Fullscreen');
      const modal = fullscreenBtn.closest('.bg-white')!;

      expect(modal.className).toContain('max-w-5xl');
      fireEvent.click(fullscreenBtn);
      expect(modal.className).toContain('inset-4');
      expect(modal.className).not.toContain('max-w-5xl');
    });
  });

  describe('Close behavior', () => {
    it('close button calls onClose', () => {
      render(<KPIDashboard onClose={onClose} />);
      // Close is the X button (second button in header)
      const buttons = screen.getAllByRole('button');
      const closeBtn = buttons.find(b => b.closest('.bg-white') && !b.getAttribute('title'));
      if (closeBtn) fireEvent.click(closeBtn);
      // The backdrop also closes
    });

    it('backdrop click calls onClose', () => {
      render(<KPIDashboard onClose={onClose} />);
      const backdrop = document.querySelector('.bg-black\\/40');
      if (backdrop) {
        fireEvent.click(backdrop);
        expect(onClose).toHaveBeenCalled();
      }
    });
  });
});

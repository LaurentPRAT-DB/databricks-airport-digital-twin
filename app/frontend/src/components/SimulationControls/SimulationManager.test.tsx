import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SimulationManager from './SimulationManager';

const mockCreateJob = vi.fn();
const mockDeleteJob = vi.fn();
const mockSaveDraft = vi.fn();
const mockUpdateDraft = vi.fn();
const mockDeleteDraft = vi.fn();
const mockRunDraft = vi.fn();

vi.mock('../../hooks/useSimulationJobs', () => ({
  useSimulationJobs: () => ({
    jobs: [
      { run_id: 1, run_name: 'JFK Storm', airport: 'JFK', status: 'SUCCESS', elapsed_seconds: 120, output_file: 'jfk_storm.json', run_page_url: null },
      { run_id: 2, run_name: 'SFO Fog', airport: 'SFO', status: 'RUNNING', elapsed_seconds: 45, output_file: null, run_page_url: null },
    ],
    isLoadingJobs: false,
    scenarios: [
      { filename: 'sfo_fog.yaml', name: 'SFO Fog', description: 'Dense fog scenario' },
      { filename: 'jfk_noreaster.yaml', name: 'JFK Noreaster', description: 'Winter storm' },
    ],
    isLoadingScenarios: false,
    createJob: mockCreateJob,
    isCreating: false,
    deleteJob: mockDeleteJob,
    isDeleting: false,
  }),
  fetchScenarioDetail: vi.fn().mockResolvedValue({
    name: 'SFO Fog',
    description: 'Dense fog scenario',
    weather_events: [{ time: '08:00', type: 'fog', severity: 'severe' }],
    runway_events: [],
    ground_events: [],
    traffic_modifiers: [],
  }),
}));

vi.mock('../../hooks/useSimulationDrafts', () => ({
  useSimulationDrafts: () => ({
    drafts: [
      {
        name: 'draft_1',
        display_name: 'Morning Rush Test',
        airport: 'SFO',
        arrivals: 300,
        departures: 300,
        duration_hours: 12,
        time_step_seconds: 2,
        seed: null,
        scenario_name: null,
        custom_scenario: null,
        skip_positions: false,
        updated_at: '2026-05-01T10:00:00Z',
        run_id: 1,
      },
    ],
    isLoadingDrafts: false,
    saveDraft: mockSaveDraft,
    isSaving: false,
    updateDraft: mockUpdateDraft,
    isUpdating: false,
    deleteDraft: mockDeleteDraft,
    isDeleting: false,
    runDraft: mockRunDraft,
    isRunningDraft: false,
  }),
}));

describe('SimulationManager', () => {
  const onClose = vi.fn();
  const onLoad = vi.fn();
  const onSelectForWindow = vi.fn();
  const defaultProps = {
    onClose,
    onLoad,
    onSelectForWindow,
    files: [
      { filename: 'sim_a.json', airport: 'SFO', total_flights: 1000, arrivals: 500, departures: 500, duration_hours: 24, size_kb: 5120, size_bytes: 5242880 },
      { filename: 'sim_b.json', airport: 'JFK', total_flights: 800, arrivals: 400, departures: 400, duration_hours: 12, size_kb: 2048, size_bytes: 2097152 },
    ],
    isLoadingSimulation: false,
    isFetchingFiles: false,
  };

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Tab rendering', () => {
    it('renders 4 tabs: Create, Saved, Load, Running', () => {
      render(<SimulationManager {...defaultProps} />);
      expect(screen.getByText('Create')).toBeInTheDocument();
      expect(screen.getByText('Saved (1)')).toBeInTheDocument();
      expect(screen.getByText('Load')).toBeInTheDocument();
      expect(screen.getByText('Running (1)')).toBeInTheDocument();
    });

    it('shows active job count badge on Running tab', () => {
      render(<SimulationManager {...defaultProps} />);
      expect(screen.getByText('Running (1)')).toBeInTheDocument();
    });

    it('shows drafts count badge on Saved tab', () => {
      render(<SimulationManager {...defaultProps} />);
      expect(screen.getByText('Saved (1)')).toBeInTheDocument();
    });
  });

  describe('Tab switching', () => {
    it('switches to Running tab on click', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Running (1)'));
      expect(screen.getByText('JFK Storm')).toBeInTheDocument();
      expect(screen.getByText('SFO Fog')).toBeInTheDocument();
    });

    it('switches to Load tab and shows files', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Load'));
      expect(screen.getAllByText(/1000 flights/).length).toBeGreaterThan(0);
      expect(screen.getAllByText(/800 flights/).length).toBeGreaterThan(0);
    });

    it('switches to Saved tab and shows drafts', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Saved (1)'));
      expect(screen.getByText('Morning Rush Test')).toBeInTheDocument();
    });
  });

  describe('Create tab', () => {
    it('renders form fields (airport, duration, arrivals, departures)', () => {
      render(<SimulationManager {...defaultProps} />);
      expect(screen.getByDisplayValue('SFO')).toBeInTheDocument();
      expect(screen.getAllByDisplayValue('500').length).toBe(2); // arrivals + departures
      expect(screen.getByDisplayValue('24')).toBeInTheDocument(); // duration
    });

    it('renders scenario mode buttons (None, Built-in, Custom)', () => {
      render(<SimulationManager {...defaultProps} />);
      expect(screen.getByText('None')).toBeInTheDocument();
      expect(screen.getByText('Built-in')).toBeInTheDocument();
      expect(screen.getByText('Custom')).toBeInTheDocument();
    });

    it('shows Run Now button that calls createJob', async () => {
      mockCreateJob.mockResolvedValue({});
      render(<SimulationManager {...defaultProps} />);
      const runBtn = screen.getByText('Run Now');
      fireEvent.click(runBtn);
      expect(mockCreateJob).toHaveBeenCalledWith(expect.objectContaining({
        airport: 'SFO',
        arrivals: 500,
        departures: 500,
        duration_hours: 24,
      }));
    });

    it('shows Save button that requires a name', async () => {
      const user = userEvent.setup();
      render(<SimulationManager {...defaultProps} />);
      const saveBtn = screen.getByText('Save');
      // Save without a name should not call saveDraft
      fireEvent.click(saveBtn);
      expect(mockSaveDraft).not.toHaveBeenCalled();

      // Type a name and save
      const nameInput = screen.getByPlaceholderText('Simulation name...');
      await user.type(nameInput, 'My Test Sim');
      fireEvent.click(saveBtn);
      await waitFor(() => {
        expect(mockSaveDraft).toHaveBeenCalledWith(expect.objectContaining({
          display_name: 'My Test Sim',
          airport: 'SFO',
        }));
      });
    });

    it('shows scenario list when Built-in mode is selected', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Built-in'));
      expect(screen.getByText('Select a scenario...')).toBeInTheDocument();
      expect(screen.getByText('SFO Fog')).toBeInTheDocument();
      expect(screen.getByText('JFK Noreaster')).toBeInTheDocument();
    });
  });

  describe('Running tab', () => {
    it('shows job status badges', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Running (1)'));
      expect(screen.getByText('SUCCESS')).toBeInTheDocument();
      expect(screen.getByText('RUNNING')).toBeInTheDocument();
    });

    it('shows Load Result button for SUCCESS jobs', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Running (1)'));
      expect(screen.getByText('Load Result')).toBeInTheDocument();
    });

    it('Load Result calls onLoad and onClose', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Running (1)'));
      fireEvent.click(screen.getByText('Load Result'));
      expect(onLoad).toHaveBeenCalledWith('jfk_storm.json');
      expect(onClose).toHaveBeenCalled();
    });

    it('delete button for running job shows confirmation', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Running (1)'));
      // Find delete buttons (trash icon buttons)
      const deleteButtons = screen.getAllByTitle(/delete|Cancel/i);
      const runningJobDelete = deleteButtons[deleteButtons.length - 1]; // last one is for running job
      fireEvent.click(runningJobDelete);
      expect(screen.getByText(/This will cancel the running job/)).toBeInTheDocument();
    });
  });

  describe('Saved tab', () => {
    it('shows draft info (name, airport, flights, duration)', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Saved (1)'));
      expect(screen.getByText('Morning Rush Test')).toBeInTheDocument();
      expect(screen.getByText(/600 flights/)).toBeInTheDocument();
      expect(screen.getByText(/12h/)).toBeInTheDocument();
    });

    it('Edit button switches to Create tab with draft loaded', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Saved (1)'));
      fireEvent.click(screen.getByText('Edit'));
      // Should switch to Create tab and show editing banner
      expect(screen.getByText(/Editing:/)).toBeInTheDocument();
      expect(screen.getByText('Morning Rush Test', { exact: false })).toBeInTheDocument();
    });

    it('Run button calls runDraft', async () => {
      mockRunDraft.mockResolvedValue({});
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Saved (1)'));
      fireEvent.click(screen.getByText('Run'));
      expect(mockRunDraft).toHaveBeenCalledWith('draft_1');
    });

    it('shows SUCCESS status badge for completed draft', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Saved (1)'));
      expect(screen.getByText('SUCCESS')).toBeInTheDocument();
    });
  });

  describe('Load tab', () => {
    it('shows available simulation files', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Load'));
      expect(screen.getByText(/SFO/)).toBeInTheDocument();
      expect(screen.getByText(/JFK/)).toBeInTheDocument();
    });

    it('clicking a file calls onLoad and onClose', () => {
      render(<SimulationManager {...defaultProps} />);
      fireEvent.click(screen.getByText('Load'));
      const fileButtons = screen.getAllByText(/1000 flights/);
      const fileButton = fileButtons[0].closest('button')!;
      fireEvent.click(fileButton);
      expect(onLoad).toHaveBeenCalledWith('sim_a.json');
      expect(onClose).toHaveBeenCalled();
    });

    it('shows loading state when isFetchingFiles is true', () => {
      render(<SimulationManager {...defaultProps} isFetchingFiles={true} />);
      fireEvent.click(screen.getByText('Load'));
      expect(screen.getByText('Loading simulation files...')).toBeInTheDocument();
    });
  });

  describe('Close behavior', () => {
    it('close button calls onClose', () => {
      render(<SimulationManager {...defaultProps} />);
      const closeBtn = screen.getByText('×');
      fireEvent.click(closeBtn);
      expect(onClose).toHaveBeenCalled();
    });

    it('backdrop click calls onClose', () => {
      render(<SimulationManager {...defaultProps} />);
      const backdrop = document.querySelector('.bg-black\\/40');
      if (backdrop) {
        fireEvent.click(backdrop);
        expect(onClose).toHaveBeenCalled();
      }
    });
  });
});

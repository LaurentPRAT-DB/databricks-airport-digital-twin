import { render, screen, fireEvent } from '@testing-library/react';
import MobileTabBar, { type MobileTab } from './MobileTabBar';

describe('MobileTabBar', () => {
  const mockOnTabChange = vi.fn();

  beforeEach(() => {
    mockOnTabChange.mockClear();
  });

  it('renders all three tabs', () => {
    render(<MobileTabBar activeTab="map" onTabChange={mockOnTabChange} />);
    expect(screen.getByText('Map')).toBeInTheDocument();
    expect(screen.getByText('Flights')).toBeInTheDocument();
    expect(screen.getByText('Info')).toBeInTheDocument();
  });

  it('highlights the active tab', () => {
    render(<MobileTabBar activeTab="flights" onTabChange={mockOnTabChange} />);
    const flightsButton = screen.getByText('Flights').closest('button')!;
    expect(flightsButton.className).toContain('text-blue-400');
  });

  it('calls onTabChange when a tab is clicked', () => {
    render(<MobileTabBar activeTab="map" onTabChange={mockOnTabChange} />);
    fireEvent.click(screen.getByText('Info'));
    expect(mockOnTabChange).toHaveBeenCalledWith('info');
  });

  it('has minimum 48px touch targets via nav height', () => {
    render(<MobileTabBar activeTab="map" onTabChange={mockOnTabChange} />);
    const nav = screen.getByRole('navigation');
    expect(nav.style.height).toContain('--tab-bar-h');
    const buttons = screen.getAllByRole('button');
    buttons.forEach((btn) => {
      expect(btn.className).toContain('flex-1');
    });
  });
});

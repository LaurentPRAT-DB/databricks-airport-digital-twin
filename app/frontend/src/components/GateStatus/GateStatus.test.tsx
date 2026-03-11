import { describe, it, expect } from 'vitest'
import { render, screen, waitFor, within } from '../../test/test-utils'
import userEvent from '@testing-library/user-event'
import GateStatus from './GateStatus'

// Helper: wait for flights to load and gate statuses to update
async function waitForFlightsAndSelectTerminalA(user: ReturnType<typeof userEvent.setup>) {
  // Wait for occupied count to reflect flight data (2 gates occupied: A3 + A5)
  await waitFor(() => {
    expect(screen.getByText(/2 Occupied/i)).toBeInTheDocument()
  })
  // Click Terminal A tab
  await user.click(screen.getByText('Terminal A'))
  // Wait for gate grid to render with flight-aware titles
  await waitFor(() => {
    expect(screen.getByTitle(/A5: ON STAND/)).toBeInTheDocument()
  })
}

describe('GateStatus — real flight occupancy', () => {
  it('shows correct occupied/available counts from flight data', async () => {
    render(<GateStatus />)

    // Mock data: UAL123 → A3 (INBOUND), SWA789 → A5 (ON STAND) = 2 occupied, 18 available
    await waitFor(() => {
      expect(screen.getByText(/2 Occupied/i)).toBeInTheDocument()
      expect(screen.getByText(/18 Available/i)).toBeInTheDocument()
    })
  })

  it('shows terminal summary with used/free counts', async () => {
    render(<GateStatus />)

    // Terminal A: 2 flights (A3 + A5), Terminal B: 0 flights
    await waitFor(() => {
      const terminalABtn = screen.getByText('Terminal A').closest('button')!
      expect(within(terminalABtn).getByText('2 used')).toBeInTheDocument()
      expect(within(terminalABtn).getByText('8 free')).toBeInTheDocument()
    })

    const terminalBBtn = screen.getByText('Terminal B').closest('button')!
    expect(within(terminalBBtn).getByText('0 used')).toBeInTheDocument()
    expect(within(terminalBBtn).getByText('10 free')).toBeInTheDocument()
  })

  it('shows gate cells with correct colors when terminal selected', async () => {
    const user = userEvent.setup()
    render(<GateStatus />)
    await waitForFlightsAndSelectTerminalA(user)

    // A5 should be ON STAND (red) — SWA789, ground, velocity=0
    const a5 = screen.getByTitle(/A5: ON STAND/)
    expect(a5.className).toMatch(/bg-red/)

    // A3 should be INBOUND (amber) — UAL123, descending
    const a3 = screen.getByTitle(/A3: INBOUND/)
    expect(a3.className).toMatch(/bg-amber/)

    // A1 should be VACANT (green)
    const a1 = screen.getByTitle(/A1: VACANT/)
    expect(a1.className).toMatch(/bg-green/)
  })

  it('clicking an occupied gate shows detail card with flight info', async () => {
    const user = userEvent.setup()
    render(<GateStatus />)
    await waitForFlightsAndSelectTerminalA(user)

    // Click gate A5 (SWA789 — ON STAND)
    await user.click(screen.getByTitle(/A5: ON STAND/))

    expect(screen.getByText('Gate A5')).toBeInTheDocument()
    expect(screen.getByText('ON STAND')).toBeInTheDocument()
    expect(screen.getByText('SWA789')).toBeInTheDocument()
    expect(screen.getByText('B738')).toBeInTheDocument()
    expect(screen.getByText(/DEN.*→.*SFO/)).toBeInTheDocument()
  })

  it('clicking an inbound gate shows INBOUND status and flight info', async () => {
    const user = userEvent.setup()
    render(<GateStatus />)
    await waitForFlightsAndSelectTerminalA(user)

    // Click gate A3 (UAL123 — INBOUND)
    await user.click(screen.getByTitle(/A3: INBOUND/))

    expect(screen.getByText('Gate A3')).toBeInTheDocument()
    expect(screen.getByText('INBOUND')).toBeInTheDocument()
    expect(screen.getByText('UAL123')).toBeInTheDocument()
    expect(screen.getByText('B737')).toBeInTheDocument()
    expect(screen.getByText(/LAX.*→.*SFO/)).toBeInTheDocument()
  })

  it('clicking a vacant gate shows VACANT with no flight info', async () => {
    const user = userEvent.setup()
    render(<GateStatus />)
    await waitForFlightsAndSelectTerminalA(user)

    // Click gate A1 (vacant)
    await user.click(screen.getByTitle(/A1: VACANT/))

    expect(screen.getByText('Gate A1')).toBeInTheDocument()
    expect(screen.getByText('VACANT')).toBeInTheDocument()
    expect(screen.getByText('No flight assigned')).toBeInTheDocument()
  })

  it('clicking same gate again dismisses detail card', async () => {
    const user = userEvent.setup()
    render(<GateStatus />)
    await waitForFlightsAndSelectTerminalA(user)

    // Open detail
    await user.click(screen.getByTitle(/A5: ON STAND/))
    expect(screen.getByText('Gate A5')).toBeInTheDocument()

    // Click same gate again → dismiss
    await user.click(screen.getByTitle(/A5: ON STAND/))
    expect(screen.queryByText('Gate A5')).not.toBeInTheDocument()
  })

  it('switching terminal clears selected gate', async () => {
    const user = userEvent.setup()
    render(<GateStatus />)
    await waitForFlightsAndSelectTerminalA(user)

    // Select a gate
    await user.click(screen.getByTitle(/A5: ON STAND/))
    expect(screen.getByText('Gate A5')).toBeInTheDocument()

    // Switch to "All" view
    await user.click(screen.getByRole('tab', { name: 'All' }))

    // Gate detail should be gone (summary view has no gate grid)
    expect(screen.queryByText('Gate A5')).not.toBeInTheDocument()
  })

  it('clicking callsign in detail card selects flight in context', async () => {
    const user = userEvent.setup()
    render(<GateStatus />)
    await waitForFlightsAndSelectTerminalA(user)

    // Open gate A5 detail
    await user.click(screen.getByTitle(/A5: ON STAND/))

    // The callsign should be a clickable button
    const callsignBtn = screen.getByText('SWA789')
    expect(callsignBtn.tagName).toBe('BUTTON')

    // Click it (calls setSelectedFlight — verify no throw)
    await user.click(callsignBtn)
  })

  it('shows gate status legend with three status colors', async () => {
    render(<GateStatus />)

    expect(screen.getByText('On Stand')).toBeInTheDocument()
    expect(screen.getByText(/Taxi In.*Inbound/)).toBeInTheDocument()
    expect(screen.getByText('Vacant')).toBeInTheDocument()
  })

  it('selected gate cell has a ring highlight', async () => {
    const user = userEvent.setup()
    render(<GateStatus />)
    await waitForFlightsAndSelectTerminalA(user)

    const a5 = screen.getByTitle(/A5: ON STAND/)
    expect(a5.className).not.toMatch(/ring-2/)

    await user.click(a5)
    expect(a5.className).toMatch(/ring-2/)
  })
})

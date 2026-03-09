/**
 * End-to-end user interaction tests
 *
 * Simulates real end-user behavior: clicking buttons, typing in inputs,
 * opening/closing panels, navigating between views. Each interaction is
 * timed so regressions in response time are caught automatically.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render as rtlRender, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { PERFORMANCE_THRESHOLDS } from './test/test-utils'
import App from './App'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 } },
  })
  return rtlRender(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  )
}

/** Wait for the backend-ready polling to resolve and the main layout to appear */
async function waitForAppReady() {
  await waitFor(
    () => {
      expect(screen.getByRole('banner')).toBeInTheDocument()
      expect(screen.getByRole('main')).toBeInTheDocument()
    },
    { timeout: 5000 },
  )
}

/** Wait until at least one flight row is rendered */
async function waitForFlights() {
  await waitFor(
    () => {
      // FlightRow renders <button> elements containing callsigns
      expect(screen.getByText(/UAL123/i)).toBeInTheDocument()
    },
    { timeout: 5000 },
  )
}

/** Measures elapsed time of an async action in ms */
async function timed(action: () => Promise<void>): Promise<number> {
  const start = performance.now()
  await action()
  return performance.now() - start
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('End-to-end user interaction flows', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  // =========================================================================
  // 1. Complete flight selection lifecycle
  // =========================================================================
  describe('Flight selection lifecycle', () => {
    it('user clicks a flight → detail panel populates → closes detail', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // --- Click on UAL123 in flight list ---
      const flightRow = screen.getByText(/UAL123/i).closest('button')!
      const selectTime = await timed(async () => {
        await user.click(flightRow)
        await waitFor(() => {
          // Detail panel should show the callsign
          expect(screen.getByText(/a12345/i)).toBeInTheDocument()
        })
      })
      expect(selectTime).toBeLessThan(PERFORMANCE_THRESHOLDS.apiResponse)

      // Detail panel shows position, movement, metadata sections
      expect(screen.getByText(/position/i)).toBeInTheDocument()
      expect(screen.getByText(/movement/i)).toBeInTheDocument()
      expect(screen.getByText(/metadata/i)).toBeInTheDocument()

      // --- Close detail panel ---
      const closeButton = screen.getByTitle(/close/i)
      const closeTime = await timed(async () => {
        await user.click(closeButton)
        await waitFor(() => {
          expect(screen.getByText(/select a flight to view details/i)).toBeInTheDocument()
        })
      })
      expect(closeTime).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)
    })

    it('selecting a descending flight shows gate recommendations', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // UAL123 is "descending" — should trigger gate recommendation section
      const flightRow = screen.getByText(/UAL123/i).closest('button')!
      await user.click(flightRow)

      await waitFor(
        () => {
          expect(screen.getByText(/gate recommendations/i)).toBeInTheDocument()
        },
        { timeout: 5000 },
      )

      // At least one gate recommendation should render (A1 from mock predictions)
      await waitFor(() => {
        expect(screen.getByText(/gate recommendations/i)).toBeInTheDocument()
        // gate_id "A1" is rendered in the recommendations section
        expect(screen.getAllByText(/A1/).length).toBeGreaterThanOrEqual(1)
      })
    })

    it('selecting a cruising flight does NOT show gate recommendations', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // DAL456 is "cruising"
      const flightRow = screen.getByText(/DAL456/i).closest('button')!
      await user.click(flightRow)

      await waitFor(() => {
        expect(screen.getByText(/b67890/i)).toBeInTheDocument()
      })

      expect(screen.queryByText(/gate recommendations/i)).not.toBeInTheDocument()
    })

    it('selecting a ground flight shows turnaround timeline and baggage', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // SWA789 is "ground"
      const flightRow = screen.getByText(/SWA789/i).closest('button')!
      await user.click(flightRow)

      await waitFor(
        () => {
          expect(screen.getByText(/turnaround/i)).toBeInTheDocument()
        },
        { timeout: 5000 },
      )

      await waitFor(
        () => {
          expect(screen.getByText(/baggage status/i)).toBeInTheDocument()
        },
        { timeout: 5000 },
      )
    })
  })

  // =========================================================================
  // 2. Flight search and filter
  // =========================================================================
  describe('Flight search and filter', () => {
    it('user types in search → list filters → selects result', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      const searchInput = screen.getByPlaceholderText(/search callsign/i)

      // Type a partial callsign
      const filterTime = await timed(async () => {
        await user.type(searchInput, 'DAL')
        await waitFor(() => {
          expect(screen.getByText('(1)')).toBeInTheDocument()
        })
      })
      expect(filterTime).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)

      // Only DAL456 visible, click it
      const flightRow = screen.getByText(/DAL456/i).closest('button')!
      await user.click(flightRow)

      await waitFor(() => {
        expect(screen.getByText(/b67890/i)).toBeInTheDocument() // icao24 in detail
      })
    })

    it('clearing search restores full list', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      const searchInput = screen.getByPlaceholderText(/search callsign/i)
      await user.type(searchInput, 'UAL')

      await waitFor(() => {
        expect(screen.getByText('(1)')).toBeInTheDocument()
      })

      await user.clear(searchInput)

      await waitFor(() => {
        expect(screen.getByText('(3)')).toBeInTheDocument()
      })
    })

    it('no-match search shows empty state', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      const searchInput = screen.getByPlaceholderText(/search callsign/i)
      await user.type(searchInput, 'ZZZZ')

      await waitFor(() => {
        expect(screen.getByText(/no flights match your search/i)).toBeInTheDocument()
      })
    })
  })

  // =========================================================================
  // 3. Sort dropdown
  // =========================================================================
  describe('Sort interaction', () => {
    it('user changes sort to altitude → list re-orders → highest first', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      const sortSelect = screen.getByLabelText(/sort/i)

      const sortTime = await timed(async () => {
        await user.selectOptions(sortSelect, 'altitude')
      })
      expect(sortTime).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)

      // DAL456 (35000ft) should be first button in the flight list
      const buttons = screen.getAllByRole('button').filter(
        (b) => b.className.includes('border-b'),
      )
      expect(buttons[0]).toHaveTextContent(/DAL456/i)
    })
  })

  // =========================================================================
  // 4. View toggle (2D / 3D)
  // =========================================================================
  describe('View toggle', () => {
    it('switch to 3D and back to 2D', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const btn2D = screen.getByRole('button', { name: /2d/i })
      const btn3D = screen.getByRole('button', { name: /3d/i })

      // Default is 2D active
      expect(btn2D).toHaveClass('bg-blue-600')
      expect(btn3D).not.toHaveClass('bg-blue-600')

      // Toggle to 3D (includes lazy-load time for 3D component)
      const to3dTime = await timed(async () => {
        await user.click(btn3D)
      })
      expect(to3dTime).toBeLessThan(PERFORMANCE_THRESHOLDS.heavyComponent)
      expect(btn3D).toHaveClass('bg-blue-600')

      // Toggle back to 2D (may still be slower due to React Suspense teardown)
      const to2dTime = await timed(async () => {
        await user.click(btn2D)
      })
      // Allow extra margin for Suspense teardown + GC
      expect(to2dTime).toBeLessThan(PERFORMANCE_THRESHOLDS.heavyComponent * 1.5)
      expect(btn2D).toHaveClass('bg-blue-600')
    })
  })

  // =========================================================================
  // 5. FIDS modal full flow
  // =========================================================================
  describe('FIDS modal', () => {
    it('open → switch tabs → verify data → close', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Open FIDS
      const fidsButton = screen.getByRole('button', { name: /fids/i })
      const openTime = await timed(async () => {
        await user.click(fidsButton)
        await waitFor(() => {
          expect(screen.getByText(/flight information display/i)).toBeInTheDocument()
        })
      })
      expect(openTime).toBeLessThan(PERFORMANCE_THRESHOLDS.apiResponse)

      // Arrivals tab should be active by default
      const arrivalsTab = screen.getByRole('button', { name: /arrivals/i })
      expect(arrivalsTab).toHaveClass('bg-blue-600')

      // Wait for schedule data to load
      await waitFor(
        () => {
          expect(screen.getByText(/UAL123/i)).toBeInTheDocument()
        },
        { timeout: 5000 },
      )

      // Switch to departures tab
      const departuresTab = screen.getByRole('button', { name: /departures/i })
      const tabSwitchTime = await timed(async () => {
        await user.click(departuresTab)
      })
      expect(tabSwitchTime).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)
      expect(departuresTab).toHaveClass('bg-blue-600')

      // Switch back to arrivals
      await user.click(arrivalsTab)
      expect(arrivalsTab).toHaveClass('bg-blue-600')

      // Close FIDS
      const closeButton = screen.getByRole('button', { name: /x/i })
      const closeTime = await timed(async () => {
        await user.click(closeButton)
        await waitFor(() => {
          expect(screen.queryByText(/flight information display/i)).not.toBeInTheDocument()
        })
      })
      expect(closeTime).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)
    })

    it('clicking tracked flight in FIDS selects it and closes modal', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // Open FIDS
      const fidsButton = screen.getByRole('button', { name: /fids/i })
      await user.click(fidsButton)

      await waitFor(() => {
        expect(screen.getByText(/flight information display/i)).toBeInTheDocument()
      })

      // Wait for arrivals data
      await waitFor(
        () => {
          // Should see "Live" badges next to tracked flights
          const liveBadges = screen.getAllByText(/live/i)
          expect(liveBadges.length).toBeGreaterThan(0)
        },
        { timeout: 5000 },
      )

      // Click on the first tracked flight row (UAL123 has a "Live" badge)
      const liveBadges = screen.getAllByText(/live/i)
      const liveRow = liveBadges[0].closest('tr')!
      const selectTime = await timed(async () => {
        await user.click(liveRow)
        // FIDS should close and detail panel should populate
        await waitFor(() => {
          expect(screen.queryByText(/flight information display/i)).not.toBeInTheDocument()
        })
      })
      expect(selectTime).toBeLessThan(PERFORMANCE_THRESHOLDS.apiResponse)

      // Flight should now be selected in detail panel
      await waitFor(() => {
        expect(screen.getByText(/a12345/i)).toBeInTheDocument()
      })
    })
  })

  // =========================================================================
  // 6. Trajectory toggle
  // =========================================================================
  describe('Trajectory toggle in detail', () => {
    it('selecting a flight auto-enables trajectory; user toggles it off', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // Select UAL123
      const flightRow = screen.getByText(/UAL123/i).closest('button')!
      await user.click(flightRow)

      await waitFor(
        () => {
          expect(screen.getByText(/show trajectory/i)).toBeInTheDocument()
        },
        { timeout: 5000 },
      )

      // Trajectory is auto-enabled on selection (FlightContext line 37)
      const toggleBtn = screen.getByText(/show trajectory/i).closest('button')!
      expect(toggleBtn).toHaveClass('bg-blue-50')

      // Toggle off
      const toggleTime = await timed(async () => {
        await user.click(toggleBtn)
        await waitFor(() => {
          const btn = screen.getByText(/show trajectory/i).closest('button')!
          expect(btn).toHaveClass('bg-slate-50')
        })
      })
      expect(toggleTime).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)

      // Toggle back on
      const btn = screen.getByText(/show trajectory/i).closest('button')!
      await user.click(btn)
      await waitFor(() => {
        const updatedBtn = screen.getByText(/show trajectory/i).closest('button')!
        expect(updatedBtn).toHaveClass('bg-blue-50')
      })
    })
  })

  // =========================================================================
  // 7. Airport selector
  // =========================================================================
  describe('Airport selector', () => {
    it('user opens dropdown → sees airport list → selects airport', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Find and click the airport selector button
      const selectorButton = screen.getByTitle(/select airport|san francisco/i)

      const openTime = await timed(async () => {
        await user.click(selectorButton)
        await waitFor(() => {
          // Should see airport list with well-known airports
          expect(screen.getByText(/John F. Kennedy International/)).toBeInTheDocument()
        })
      })
      expect(openTime).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)

      // Verify several airports are listed (use exact names to avoid multiple matches)
      expect(screen.getByText(/Los Angeles International/)).toBeInTheDocument()
      expect(screen.getByText(/London Heathrow/)).toBeInTheDocument()

      // Select JFK
      const jfkButton = screen.getByText(/KJFK/).closest('button')!
      const selectTime = await timed(async () => {
        await user.click(jfkButton)
      })
      expect(selectTime).toBeLessThan(PERFORMANCE_THRESHOLDS.apiResponse)

      // Dropdown should close
      await waitFor(() => {
        expect(screen.queryByText(/john f. kennedy/i)).not.toBeInTheDocument()
      })
    })

    it('user enters custom ICAO code', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Open selector
      const selectorButton = screen.getByTitle(/select airport|san francisco/i)
      await user.click(selectorButton)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/enter icao code/i)).toBeInTheDocument()
      })

      // Type custom code
      const icaoInput = screen.getByPlaceholderText(/enter icao code/i)
      await user.type(icaoInput, 'EDDF')

      // Click "Load" button
      const loadButton = screen.getByRole('button', { name: /load/i })
      expect(loadButton).not.toBeDisabled()

      await user.click(loadButton)

      // Dropdown should close after loading
      await waitFor(() => {
        expect(screen.queryByPlaceholderText(/enter icao code/i)).not.toBeInTheDocument()
      })
    })

    it('custom ICAO input disables Load button when too short', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const selectorButton = screen.getByTitle(/select airport|san francisco/i)
      await user.click(selectorButton)

      await waitFor(() => {
        expect(screen.getByPlaceholderText(/enter icao code/i)).toBeInTheDocument()
      })

      // Load button should be disabled with empty input
      const loadButton = screen.getByRole('button', { name: /load/i })
      expect(loadButton).toBeDisabled()

      // Type only 2 chars — still disabled
      const icaoInput = screen.getByPlaceholderText(/enter icao code/i)
      await user.type(icaoInput, 'KS')
      expect(loadButton).toBeDisabled()
    })
  })

  // =========================================================================
  // 8. Platform links dropdown
  // =========================================================================
  describe('Platform links', () => {
    it('user opens platform menu → sees links → closes it', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const platformButton = screen.getByTitle(/databricks platform links/i)

      const openTime = await timed(async () => {
        await user.click(platformButton)
        await waitFor(() => {
          expect(screen.getByText(/databricks platform/i)).toBeInTheDocument()
        })
      })
      expect(openTime).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)

      // Check key links are rendered (use getAllByText for labels that appear in both title and description)
      expect(screen.getByText(/Flight Dashboard/)).toBeInTheDocument()
      expect(screen.getByText(/Ask Genie/)).toBeInTheDocument()
      expect(screen.getByText(/Data Lineage/)).toBeInTheDocument()
      expect(screen.getByText(/ML Experiments/)).toBeInTheDocument()
      // "Unity Catalog" appears in both a link label and a description, use getAllByText
      const ucMatches = screen.getAllByText(/Unity Catalog/)
      expect(ucMatches.length).toBeGreaterThan(0)

      // Platform links should be <a> tags with target _blank
      // Scope to the dropdown container (the outer rounded-lg div with border)
      const dropdownHeader = screen.getByText(/Access platform features/)
      // Go up to the outer dropdown container that has all links
      const dropdown = dropdownHeader.closest('[class*="rounded-lg shadow-xl"]')!
      const links = within(dropdown as HTMLElement).getAllByRole('link')
      expect(links.length).toBe(5) // 5 platform links
      links.forEach((link) => {
        expect(link).toHaveAttribute('target', '_blank')
      })

      // Close by clicking Platform button again
      await user.click(platformButton)

      await waitFor(() => {
        expect(screen.queryByText(/Access platform features/)).not.toBeInTheDocument()
      })
    })
  })

  // =========================================================================
  // 9. Gate status panel
  // =========================================================================
  describe('Gate status panel', () => {
    it('renders gate grid with available/occupied counts', async () => {
      renderApp()
      await waitForAppReady()

      // Gate status should be visible in right panel
      expect(screen.getByText(/gate status/i)).toBeInTheDocument()

      // Should show at least one terminal label (real OSM names or fallback)
      const terminalLabels = screen.getAllByText(/terminal/i)
      expect(terminalLabels.length).toBeGreaterThanOrEqual(1)

      // Should show available/occupied count labels
      expect(screen.getByText(/available/i)).toBeInTheDocument()
      expect(screen.getByText(/occupied/i)).toBeInTheDocument()

      // Should show congestion legend
      expect(screen.getByText(/area congestion/i)).toBeInTheDocument()
    })
  })

  // =========================================================================
  // 10. Header status indicators
  // =========================================================================
  describe('Header indicators', () => {
    it('shows flight count and connection status', async () => {
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // Flight count pill in header
      const header = screen.getByRole('banner')
      expect(within(header).getByText(/Flights:/)).toBeInTheDocument()

      // Phase legend in header
      expect(within(header).getByText('Ground')).toBeInTheDocument()
      expect(within(header).getByText('Climbing')).toBeInTheDocument()

      // Connection status - may be "Connected" or "Updating" depending on timing
      await waitFor(() => {
        const statusText = within(header).getByText(/Connected|Updating|Error/)
        expect(statusText).toBeInTheDocument()
      })
    })

    it('shows demo mode badge for synthetic data', async () => {
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        expect(screen.getByText(/demo mode/i)).toBeInTheDocument()
      })
    })
  })

  // =========================================================================
  // 11. Combined flow: search + sort + select + FIDS
  // =========================================================================
  describe('Combined multi-step user flow', () => {
    it('sort by altitude → search → select → open FIDS → close → verify state', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // Step 1: Sort by altitude
      const sortSelect = screen.getByLabelText(/sort/i)
      await user.selectOptions(sortSelect, 'altitude')

      // Step 2: Search for "DAL"
      const searchInput = screen.getByPlaceholderText(/search callsign/i)
      await user.type(searchInput, 'DAL')
      await waitFor(() => {
        expect(screen.getByText('(1)')).toBeInTheDocument()
      })

      // Step 3: Select DAL456
      const flightRow = screen.getByText(/DAL456/i).closest('button')!
      await user.click(flightRow)
      await waitFor(() => {
        expect(screen.getByText(/b67890/i)).toBeInTheDocument()
      })

      // Step 4: Open FIDS
      const fidsButton = screen.getByRole('button', { name: /fids/i })
      await user.click(fidsButton)
      await waitFor(() => {
        expect(screen.getByText(/flight information display/i)).toBeInTheDocument()
      })

      // Step 5: Close FIDS
      const closeButton = screen.getByRole('button', { name: /x/i })
      await user.click(closeButton)
      await waitFor(() => {
        expect(screen.queryByText(/flight information display/i)).not.toBeInTheDocument()
      })

      // Step 6: Verify flight is still selected after FIDS round-trip
      expect(screen.getByText(/b67890/i)).toBeInTheDocument()

      // Step 7: Clear search, verify sort is preserved
      await user.clear(searchInput)
      await waitFor(() => {
        expect(screen.getByText('(3)')).toBeInTheDocument()
      })
      expect(sortSelect).toHaveValue('altitude')
    })
  })

  // =========================================================================
  // 12. Delay prediction detail (response time)
  // =========================================================================
  describe('Delay prediction loading performance', () => {
    it('delay prediction loads within API threshold after flight selection', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // Select UAL123 (has mock delay prediction)
      const flightRow = screen.getByText(/UAL123/i).closest('button')!
      const predictionTime = await timed(async () => {
        await user.click(flightRow)
        await waitFor(
          () => {
            expect(screen.getByText(/expected delay/i)).toBeInTheDocument()
          },
          { timeout: 5000 },
        )
      })
      expect(predictionTime).toBeLessThan(PERFORMANCE_THRESHOLDS.apiResponse)

      // Verify prediction data renders
      expect(screen.getByText(/confidence/i)).toBeInTheDocument()
      expect(screen.getByText(/slight delay/i)).toBeInTheDocument()
    })
  })

  // =========================================================================
  // 13. Weather widget
  // =========================================================================
  describe('Weather widget', () => {
    it('weather data loads in header', async () => {
      renderApp()
      await waitForAppReady()

      // WeatherWidget shows METAR data
      await waitFor(
        () => {
          expect(screen.getByText(/KSFO/)).toBeInTheDocument()
        },
        { timeout: 5000 },
      )
    })
  })

  // =========================================================================
  // 14. Keyboard navigation
  // =========================================================================
  describe('Keyboard accessibility', () => {
    it('all interactive elements are tabbable', async () => {
      renderApp()
      await waitForAppReady()

      const buttons = screen.getAllByRole('button')
      buttons.forEach((button) => {
        // Buttons should not have tabIndex=-1 (hidden from tab order)
        expect(button.tabIndex).not.toBe(-1)
      })

      // Search input should be accessible
      const searchInput = screen.getByPlaceholderText(/search callsign/i)
      expect(searchInput.tabIndex).not.toBe(-1)

      // Sort select should be accessible
      const sortSelect = screen.getByLabelText(/sort/i)
      expect(sortSelect.tabIndex).not.toBe(-1)
    })
  })

  // =========================================================================
  // 15. Rapid sequential interactions (stress test)
  // =========================================================================
  describe('Rapid user interactions', () => {
    it('rapidly selecting different flights does not crash', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // Rapidly click through all three flights
      const ual = screen.getByText(/UAL123/i).closest('button')!
      const dal = screen.getByText(/DAL456/i).closest('button')!
      const swa = screen.getByText(/SWA789/i).closest('button')!

      await user.click(ual)
      await user.click(dal)
      await user.click(swa)
      await user.click(ual)
      await user.click(dal)

      // Should settle on DAL456 being selected
      await waitFor(() => {
        expect(screen.getByText(/b67890/i)).toBeInTheDocument()
      })
    })

    it('rapidly toggling FIDS open/close does not crash', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const fidsButton = screen.getByRole('button', { name: /fids/i })

      // Open
      await user.click(fidsButton)
      await waitFor(() => {
        expect(screen.getByText(/flight information display/i)).toBeInTheDocument()
      })

      // Close
      const closeButton = screen.getByRole('button', { name: /x/i })
      await user.click(closeButton)
      await waitFor(() => {
        expect(screen.queryByText(/flight information display/i)).not.toBeInTheDocument()
      })

      // Open again immediately
      await user.click(fidsButton)
      await waitFor(() => {
        expect(screen.getByText(/flight information display/i)).toBeInTheDocument()
      })
    })

    it('rapidly toggling 2D/3D does not crash', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const btn2D = screen.getByRole('button', { name: /2d/i })
      const btn3D = screen.getByRole('button', { name: /3d/i })

      await user.click(btn3D)
      await user.click(btn2D)
      await user.click(btn3D)
      await user.click(btn2D)

      // Should settle on 2D
      expect(btn2D).toHaveClass('bg-blue-600')
    })
  })
})

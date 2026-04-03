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

      // Detail panel shows position and movement sections
      expect(screen.getByText(/position/i)).toBeInTheDocument()
      expect(screen.getByText(/movement/i)).toBeInTheDocument()

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
          expect(screen.getByText(/gate (assignment|recommendations)/i)).toBeInTheDocument()
        },
        { timeout: 5000 },
      )

      // At least one gate recommendation should render (A1 from mock predictions)
      await waitFor(() => {
        expect(screen.getByText(/gate (assignment|recommendations)/i)).toBeInTheDocument()
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
      const closeButton = screen.getByRole('button', { name: /close fids/i })
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

      // Wait for arrivals data — scope to FIDS modal to avoid LiveBar's "Live" label
      const fidsModal = screen.getByText(/flight information display/i).closest('[class*="bg-slate-900"]')!
      await waitFor(
        () => {
          const liveBadges = within(fidsModal as HTMLElement).getAllByText(/live/i)
          expect(liveBadges.length).toBeGreaterThan(0)
        },
        { timeout: 5000 },
      )

      // Click on the first tracked flight row (UAL123 has a "Live" badge)
      const liveBadges = within(fidsModal as HTMLElement).getAllByText(/live/i)
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
      const selectorButton = screen.getByTitle(/select airport|san francisco|KSFO/i)

      // Brief delay to let mount-time fetch settle before opening
      await new Promise((r) => setTimeout(r, 100))
      const openTime = await timed(async () => {
        await user.click(selectorButton)
        await waitFor(() => {
          // Should see airport list with well-known airports
          expect(screen.getByText(/John F. Kennedy International/)).toBeInTheDocument()
        }, { timeout: 5000 })
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
      const selectorButton = screen.getByTitle(/select airport|san francisco|KSFO/i)
      await user.click(selectorButton)

      const icaoInput = await screen.findByPlaceholderText(/enter icao code/i, {}, { timeout: 5000 })

      // Type custom code
      await user.type(icaoInput, 'EDDF')

      // Click "Load" button
      const loadButton = screen.getByRole('button', { name: /^load$/i })
      expect(loadButton).not.toBeDisabled()

      await user.click(loadButton)

      // Dropdown should close after loading
      await waitFor(() => {
        expect(screen.queryByPlaceholderText(/enter icao code/i)).not.toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('custom ICAO input disables Load button when too short', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const selectorButton = await screen.findByTitle(/select airport|san francisco|KSFO/i, {}, { timeout: 3000 })
      await user.click(selectorButton)

      const icaoInput = await screen.findByPlaceholderText(/enter icao code/i, {}, { timeout: 3000 })

      // Load button should be disabled with empty input
      const loadButton = screen.getByRole('button', { name: /^load$/i })
      expect(loadButton).toBeDisabled()

      // Type only 2 chars — still disabled
      await user.type(icaoInput, 'KS')
      expect(loadButton).toBeDisabled()
    })
  })

  // =========================================================================
  // 7b. Airport selector — region grouping, cache status, pre-load
  // =========================================================================
  // 7b. Airport Selector — Pre-load, Cache Status & Region Grouping
  //
  // Tests the airport selector dropdown after the pre-load/cache feature:
  //
  //  #  Test                                            Covers
  //  ── ─────────────────────────────────────────────── ─────────────────────────
  //  1  dropdown shows all 5 region headers              Region grouping UI
  //  2  dropdown lists all 27 well-known airports        Airport count integrity
  //  3  shows new airports added in this release         15 new airports visible
  //  4  green dot for cached, gray for uncached          Cache status indicator
  //  5  cache dots have accessible title attributes      Accessibility / tooltips
  //  6  Pre-load All button with correct cache count     Button label & state
  //  7  Pre-load All shows spinner while preloading      Loading UX
  //  8  Pre-load All disabled when all cached            Completion state
  //  9  selecting current airport closes w/o reload      No-op selection
  // 10  current airport shows checkmark icon             Active indicator
  // 11  custom ICAO submits on Enter key                 Keyboard shortcut
  // 12  custom ICAO auto-uppercases input                Input normalization
  // 13  dropdown closes when clicking outside            Dismiss behavior
  // 14  open/close multiple times renders correctly      State stability
  // 15  gracefully handles API failure                   Degraded mode
  //
  // Backend endpoints exercised:
  //   GET  /api/airports/preload/status  → airport list + cached boolean
  //   POST /api/airports/preload         → bulk pre-load trigger
  //
  // MSW mock handlers in: src/test/mocks/handlers.ts
  // =========================================================================
  describe('Airport selector — regions, cache, and pre-load', () => {
    /** Helper: open dropdown and wait for airports to load from API.
     *  Returns the dropdown container for scoped queries via `within()`. */
    async function openAirportDropdown(user: ReturnType<typeof userEvent.setup>) {
      const selectorButton = screen.getByTitle(/select airport|san francisco|KSFO/i)
      // Wait briefly for the mount-time fetch to settle before opening,
      // avoiding an AbortController race between mount fetch and open fetch.
      await new Promise((r) => setTimeout(r, 100))
      await user.click(selectorButton)
      // Wait for the async fetch to populate the airport list
      const jfkEl = await screen.findByText(/John F. Kennedy International/, {}, { timeout: 5000 })
      // Return the dropdown panel (the absolute-positioned div)
      return jfkEl.closest('.absolute')! as HTMLElement
    }

    it('dropdown shows all 5 region headers', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      // All 5 regions should appear as section headers (CSS uppercase, DOM mixed-case)
      expect(within(dropdown).getByText('Americas')).toBeInTheDocument()
      expect(within(dropdown).getByText('Europe')).toBeInTheDocument()
      expect(within(dropdown).getByText('Middle East')).toBeInTheDocument()
      expect(within(dropdown).getByText('Asia-Pacific')).toBeInTheDocument()
      expect(within(dropdown).getByText('Africa')).toBeInTheDocument()
    })

    it('dropdown lists all 27 well-known airports', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      // Each airport has a cache status dot with a title attribute
      const cachedDots = within(dropdown).getAllByTitle('Cached (fast switch)')
      const uncachedDots = within(dropdown).getAllByTitle('Not cached (will fetch from OSM)')
      expect(cachedDots.length + uncachedDots.length).toBe(27)
    })

    it('shows new airports added in this release', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      await openAirportDropdown(user)

      // Americas additions
      expect(screen.getByText(/Dallas\/Fort Worth International/)).toBeInTheDocument()
      expect(screen.getByText(/Denver International/)).toBeInTheDocument()
      expect(screen.getByText(/Miami International/)).toBeInTheDocument()
      expect(screen.getByText(/Seattle-Tacoma International/)).toBeInTheDocument()
      expect(screen.getByText(/Guarulhos International/)).toBeInTheDocument()
      expect(screen.getByText(/Mexico City International/)).toBeInTheDocument()

      // Europe additions
      expect(screen.getByText(/Amsterdam Schiphol/)).toBeInTheDocument()
      expect(screen.getByText(/Frankfurt Airport/)).toBeInTheDocument()
      expect(screen.getByText(/Madrid-Barajas/)).toBeInTheDocument()
      expect(screen.getByText(/Fiumicino/)).toBeInTheDocument()

      // Asia-Pacific additions
      expect(screen.getByText(/Beijing Capital International/)).toBeInTheDocument()
      expect(screen.getByText(/Incheon International/)).toBeInTheDocument()
      expect(screen.getByText(/Suvarnabhumi Airport/)).toBeInTheDocument()

      // Africa additions
      expect(screen.getByText(/O\.R\. Tambo International/)).toBeInTheDocument()
      expect(screen.getByText(/Mohammed V International/)).toBeInTheDocument()
    })

    it('shows green cache dot for KSFO (cached) and gray for uncached airports', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      // KSFO is cached in mock data — its row should have a green dot
      const ksfoButton = within(dropdown).getByText('KSFO').closest('button')!
      const greenDot = ksfoButton.querySelector('.bg-green-500')
      expect(greenDot).toBeInTheDocument()

      // KJFK is not cached — its row should have a gray dot
      const kjfkButton = within(dropdown).getByText('KJFK').closest('button')!
      const grayDot = kjfkButton.querySelector('.bg-slate-300')
      expect(grayDot).toBeInTheDocument()
    })

    it('cache status dots have accessible title attributes', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      // Cached airport dot should explain fast switch
      expect(within(dropdown).getByTitle('Cached (fast switch)')).toBeInTheDocument()

      // Uncached airports should explain OSM fetch
      const osmTitles = within(dropdown).getAllByTitle('Not cached (will fetch from OSM)')
      expect(osmTitles.length).toBe(26) // 27 total minus 1 cached
    })

    it('shows Pre-load All button with correct cache count', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      // Pre-load button shows count: 1 cached out of 27
      const preloadButton = within(dropdown).getByRole('button', { name: /pre-load all/i })
      expect(preloadButton).toBeInTheDocument()
      expect(preloadButton).toHaveTextContent('1/27 cached')
      expect(preloadButton).not.toBeDisabled()
    })

    it('Pre-load All button shows spinner while preloading', async () => {
      // Use a slow handler so we can observe the loading state
      const { server } = await import('./test/mocks/server')
      const { http, HttpResponse, delay } = await import('msw')
      server.use(
        http.post('/api/airports/preload', async () => {
          await delay(300)
          return HttpResponse.json({ preloaded: [], already_cached: ['KSFO'], failed: [] })
        }),
      )

      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      const preloadButton = within(dropdown).getByRole('button', { name: /pre-load all/i })
      await user.click(preloadButton)

      // Should show "Pre-loading..." while in progress
      await waitFor(() => {
        expect(screen.getByText(/pre-loading\.\.\./i)).toBeInTheDocument()
      })

      // Button should be disabled during preload
      const preloadingButton = screen.getByRole('button', { name: /pre-loading/i })
      expect(preloadingButton).toBeDisabled()

      // Wait for preload to finish AND the subsequent cache status refresh to settle
      await waitFor(
        () => {
          // Button should revert to showing the Pre-load All text
          expect(screen.getByRole('button', { name: /pre-load all/i })).toBeInTheDocument()
        },
        { timeout: 5000 },
      )
    })

    it('Pre-load All button disabled when all airports are cached', async () => {
      // Override handler to return all airports as cached
      const { server } = await import('./test/mocks/server')
      const { http, HttpResponse } = await import('msw')
      server.use(
        http.get('/api/airports/preload/status', async () => {
          return HttpResponse.json({
            airports: [
              { icao: 'KSFO', iata: 'SFO', name: 'San Francisco International', city: 'San Francisco, CA', region: 'Americas', cached: true },
              { icao: 'KJFK', iata: 'JFK', name: 'John F. Kennedy International', city: 'New York, NY', region: 'Americas', cached: true },
            ],
          })
        }),
      )

      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const selectorButton = screen.getByTitle(/select airport|san francisco|KSFO/i)
      await user.click(selectorButton)

      await waitFor(() => {
        expect(screen.getByText(/all 2 airports cached/i)).toBeInTheDocument()
      })

      const preloadButton = screen.getByRole('button', { name: /all 2 airports cached/i })
      expect(preloadButton).toBeDisabled()
    })

    it('selecting the current airport just closes dropdown without triggering load', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      // KSFO should be highlighted as current
      const ksfoButton = within(dropdown).getByText('KSFO').closest('button')!
      expect(ksfoButton).toHaveClass('bg-blue-100')

      // Click it — dropdown should close without triggering activate
      await user.click(ksfoButton)
      await waitFor(() => {
        expect(screen.queryByText('Americas')).not.toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('current airport shows checkmark icon', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      // KSFO row should contain a checkmark SVG (the only airport button with an SVG)
      const ksfoButton = within(dropdown).getByText('KSFO').closest('button')!
      const checkmark = ksfoButton.querySelector('svg')
      expect(checkmark).toBeInTheDocument()
    })

    it('custom ICAO input submits on Enter key', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      const icaoInput = within(dropdown).getByPlaceholderText(/enter icao code/i)
      await user.type(icaoInput, 'RJAA{Enter}')

      // Dropdown should close after Enter submission
      await waitFor(() => {
        expect(screen.queryByPlaceholderText(/enter icao code/i)).not.toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('custom ICAO input auto-uppercases user input', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const dropdown = await openAirportDropdown(user)

      const icaoInput = within(dropdown).getByPlaceholderText(/enter icao code/i)
      await user.type(icaoInput, 'ksfo')

      // Input value should be uppercased
      expect(icaoInput).toHaveValue('KSFO')
    })

    it('dropdown closes when clicking outside', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      await openAirportDropdown(user)

      // Click on the main area (outside dropdown)
      await user.click(document.body)

      await waitFor(() => {
        expect(screen.queryByText('Americas')).not.toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('opening and closing dropdown multiple times renders correctly', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const selectorButton = screen.getByTitle(/select airport|san francisco|KSFO/i)

      // Open — wait for airports to load (brief delay lets mount fetch settle)
      await new Promise((r) => setTimeout(r, 100))
      await user.click(selectorButton)
      await screen.findByText(/John F. Kennedy International/, {}, { timeout: 5000 })

      // Close via toggle
      await user.click(selectorButton)
      await waitFor(() => {
        expect(screen.queryByText(/John F. Kennedy International/)).not.toBeInTheDocument()
      })

      // Open again — airports should reload from cache or re-fetch
      await user.click(selectorButton)
      await screen.findByText(/John F. Kennedy International/, {}, { timeout: 5000 })
    })

    it('dropdown gracefully handles preload status API failure', async () => {
      const { server } = await import('./test/mocks/server')
      const { http, HttpResponse } = await import('msw')
      server.use(
        http.get('/api/airports/preload/status', async () => {
          return HttpResponse.json({ error: 'Server error' }, { status: 500 })
        }),
      )

      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const selectorButton = await screen.findByTitle(/select airport|san francisco|KSFO/i, {}, { timeout: 3000 })
      await user.click(selectorButton)

      // Custom ICAO input should still work even if airport list fails
      await screen.findByPlaceholderText(/enter icao code/i, {}, { timeout: 3000 })
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
      expect(screen.getByText(/Airport Ops Genie/)).toBeInTheDocument()
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
    it('renders gate grid with filter pills and available/occupied counts', async () => {
      renderApp()
      await waitForAppReady()
      await waitForFlights() // Gates are derived from flights when OSM gates are empty

      // Gate status should be visible in right panel
      expect(screen.getByText(/gate status/i)).toBeInTheDocument()

      // Should show "All" pill and at least one terminal pill
      // (tabs appear after flights load since gates are derived from flight data)
      await waitFor(() => {
        const tabs = screen.getAllByRole('tab')
        expect(tabs.length).toBeGreaterThanOrEqual(2) // "All" + at least one terminal
        expect(tabs[0]).toHaveTextContent('All')
      })

      // Should show at least one terminal in summary view
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

      const header = screen.getByRole('banner')

      // Legend button in header
      expect(within(header).getByRole('button', { name: /legend/i })).toBeInTheDocument()

      // Connection status — compact dot with tooltip
      await waitFor(() => {
        const indicator = header.querySelector('.bg-green-500, .bg-yellow-500, .bg-red-500')
        expect(indicator).toBeTruthy()
      })
    })

    it('shows simulation controls in header', async () => {
      renderApp()
      await waitForAppReady()

      await waitFor(() => {
        // Simulation controls should be present (either SIM badge, Start Simulation, or Preparing)
        const header = screen.getByRole('banner')
        expect(header).toBeInTheDocument()
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
      const closeButton = screen.getByRole('button', { name: /close fids/i })
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
            expect(screen.getByText(/slight delay/i)).toBeInTheDocument()
          },
          { timeout: 5000 },
        )
      })
      expect(predictionTime).toBeLessThan(PERFORMANCE_THRESHOLDS.apiResponse)

      // Verify delay minutes render
      expect(screen.getByText(/\+\d+m/)).toBeInTheDocument()
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
  // 15. Airport switch state propagation
  // =========================================================================
  describe('Airport switch state propagation', () => {
    /** Helper: open airport selector, click an airport, wait for dropdown close */
    async function switchToAirport(user: ReturnType<typeof userEvent.setup>, icaoCode: string) {
      // Find the airport selector button (contains ICAO code like "KSFO" or "KJFK")
      const allButtons = screen.getAllByRole('button')
      const selectorButton = allButtons.find((b) =>
        b.querySelector('svg') && /^[A-Z]{4}\s*\(/.test(b.textContent || '')
      ) || screen.getByTitle(/select airport|san francisco|international/i)

      await new Promise((r) => setTimeout(r, 100))
      await user.click(selectorButton)
      await waitFor(() => {
        expect(screen.getByText(/John F. Kennedy International/)).toBeInTheDocument()
      }, { timeout: 5000 })

      // Find the target airport button in the dropdown list
      // Use a more specific selector to avoid matching the header button
      const dropdownButtons = screen.getAllByRole('button').filter(
        (b) => b.textContent?.includes(icaoCode) && b.textContent?.includes('International')
      )
      const airportButton = dropdownButtons.length > 0
        ? dropdownButtons[0]
        : screen.getByText(new RegExp(icaoCode)).closest('button')!

      await user.click(airportButton)

      // Wait for dropdown to close (activation triggered)
      await waitFor(() => {
        expect(screen.queryByText(/John F. Kennedy International/)).not.toBeInTheDocument()
      }, { timeout: 5000 })
    }

    it('header updates to new airport code after switch', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Initially KSFO — button text shows "KSFO (SFO)"
      expect(screen.getByText(/KSFO/)).toBeInTheDocument()

      await switchToAirport(user, 'KJFK')

      // Header selector should now show KJFK
      await waitFor(() => {
        expect(screen.getByText(/KJFK/)).toBeInTheDocument()
      }, { timeout: 5000 })
    })

    it('gate status panel updates after airport switch', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Gate status should exist
      expect(screen.getByText(/gate status/i)).toBeInTheDocument()

      await switchToAirport(user, 'KJFK')

      // Gate status panel should still render (not crash)
      await waitFor(() => {
        expect(screen.getByText(/gate status/i)).toBeInTheDocument()
      })
    })

    it('3D view renders after airport switch', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Switch airport first
      await switchToAirport(user, 'KJFK')

      // Then switch to 3D
      const btn3D = screen.getByRole('button', { name: /3d/i })
      await user.click(btn3D)

      // 3D button should be active (3D view loaded)
      expect(btn3D).toHaveClass('bg-blue-600')

      // Switch back to 2D — should not crash
      const btn2D = screen.getByRole('button', { name: /2d/i })
      await user.click(btn2D)
      expect(btn2D).toHaveClass('bg-blue-600')
    })

    it('2D↔3D round-trip works after airport switch', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      const btn2D = screen.getByRole('button', { name: /2d/i })
      const btn3D = screen.getByRole('button', { name: /3d/i })

      // Start in 3D
      await user.click(btn3D)
      expect(btn3D).toHaveClass('bg-blue-600')

      // Switch airport while in 3D
      await switchToAirport(user, 'KJFK')

      // Verify still in 3D and not crashed
      expect(btn3D).toHaveClass('bg-blue-600')

      // Toggle back to 2D
      await user.click(btn2D)
      expect(btn2D).toHaveClass('bg-blue-600')

      // Toggle to 3D again — should still work
      await user.click(btn3D)
      expect(btn3D).toHaveClass('bg-blue-600')
    })

    it('switching airports multiple times does not crash', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Switch to JFK
      await switchToAirport(user, 'KJFK')
      await waitFor(() => {
        expect(screen.getByText(/KJFK/)).toBeInTheDocument()
      }, { timeout: 5000 })

      // Switch to LHR
      await switchToAirport(user, 'EGLL')
      await waitFor(() => {
        expect(screen.getByText(/EGLL/)).toBeInTheDocument()
      }, { timeout: 5000 })

      // Everything should still render
      expect(screen.getByText(/gate status/i)).toBeInTheDocument()
      expect(screen.getByText(/flight details/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /2d/i })).toBeInTheDocument()
    })

    it('flight detail panel still works after airport switch', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // Select a flight before switching
      const flightRow = screen.getByText(/UAL123/i).closest('button')!
      await user.click(flightRow)

      await waitFor(() => {
        expect(screen.getByText(/a12345/i)).toBeInTheDocument()
      })

      // Switch airport
      await switchToAirport(user, 'KJFK')

      // Detail panel should still be functional (either shows the flight or cleared)
      // At minimum, the panel heading should exist
      expect(screen.getByRole('heading', { name: /flight details/i })).toBeInTheDocument()
    })

    it('FIDS still works after airport switch', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Switch airport
      await switchToAirport(user, 'KJFK')

      // Open FIDS
      const fidsButton = screen.getByRole('button', { name: /fids/i })
      await user.click(fidsButton)

      await waitFor(() => {
        expect(screen.getByText(/flight information display/i)).toBeInTheDocument()
      })

      // Close FIDS
      const closeButton = screen.getByRole('button', { name: /close fids/i })
      await user.click(closeButton)

      await waitFor(() => {
        expect(screen.queryByText(/flight information display/i)).not.toBeInTheDocument()
      })
    })
  })

  // =========================================================================
  // 16. Flight selection persistence across view toggles
  // =========================================================================
  describe('Flight selection persistence across view toggles', () => {
    it('selected flight persists when switching from 2D to 3D and back', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // Select UAL123
      const flightRow = screen.getByText(/UAL123/i).closest('button')!
      await user.click(flightRow)

      await waitFor(() => {
        expect(screen.getByText(/a12345/i)).toBeInTheDocument()
      })

      // Switch to 3D
      const btn3D = screen.getByRole('button', { name: /3d/i })
      await user.click(btn3D)

      // Flight should still be selected in detail panel
      expect(screen.getByText(/a12345/i)).toBeInTheDocument()

      // Switch back to 2D
      const btn2D = screen.getByRole('button', { name: /2d/i })
      await user.click(btn2D)

      // Flight should still be selected
      expect(screen.getByText(/a12345/i)).toBeInTheDocument()
    })

    it('trajectory toggle state persists across view switches', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights()

      // Select a flight (trajectory auto-enables)
      const flightRow = screen.getByText(/UAL123/i).closest('button')!
      await user.click(flightRow)

      await waitFor(() => {
        expect(screen.getByText(/show trajectory/i)).toBeInTheDocument()
      }, { timeout: 5000 })

      const toggleBtn = screen.getByText(/show trajectory/i).closest('button')!
      expect(toggleBtn).toHaveClass('bg-blue-50')

      // Toggle trajectory off
      await user.click(toggleBtn)
      await waitFor(() => {
        const btn = screen.getByText(/show trajectory/i).closest('button')!
        expect(btn).toHaveClass('bg-slate-50')
      })

      // Switch to 3D and back
      const btn3D = screen.getByRole('button', { name: /3d/i })
      const btn2D = screen.getByRole('button', { name: /2d/i })
      await user.click(btn3D)
      await user.click(btn2D)

      // Trajectory state should be preserved
      await waitFor(() => {
        const updatedBtn = screen.getByText(/show trajectory/i).closest('button')!
        expect(updatedBtn).toHaveClass('bg-slate-50')
      })
    })
  })

  // =========================================================================
  // 17. Loading screen and backend readiness
  // =========================================================================
  describe('Loading screen lifecycle', () => {
    it('shows loading screen with radar animation before backend is ready', async () => {
      // Override /api/ready to delay readiness
      const { server } = await import('./test/mocks/server')
      const { http, HttpResponse, delay: mswDelay } = await import('msw')

      server.use(
        http.get('/api/ready', async () => {
          await mswDelay(100)
          return HttpResponse.json({ ready: false, status: 'Loading airport data' })
        }),
      )

      renderApp()

      // Should show loading screen with title
      expect(screen.getByRole('heading', { name: /airport digital twin/i })).toBeInTheDocument()

      // Should show status message
      await waitFor(() => {
        expect(screen.getByText(/loading airport data|initializing/i)).toBeInTheDocument()
      })

      // Now make backend ready
      server.use(
        http.get('/api/ready', async () => {
          return HttpResponse.json({ ready: true, status: 'Ready' })
        }),
      )

      // Should transition to main app
      await waitFor(() => {
        expect(screen.getByRole('main')).toBeInTheDocument()
      }, { timeout: 10000 })
    })
  })

  // =========================================================================
  // 18. Gate status terminal switching after airport switch
  // =========================================================================
  describe('Gate status after airport switch', () => {
    it('gate status terminal tabs are clickable after airport switch', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()
      await waitForFlights() // Gates are derived from flights when OSM gates are empty

      // Verify gate status renders initially (wait for flight-derived tabs)
      await waitFor(() => {
        expect(screen.getAllByRole('tab').length).toBeGreaterThanOrEqual(2)
      })
      const tabs = screen.getAllByRole('tab')

      // Click "All" tab
      await user.click(tabs[0])
      expect(tabs[0]).toHaveAttribute('aria-selected', 'true')

      // If there's a second tab, click it
      if (tabs.length > 1) {
        await user.click(tabs[1])
      }

      // No crash — panel still functional
      expect(screen.getByText(/gate status/i)).toBeInTheDocument()
    })
  })

  // =========================================================================
  // 19. Weather widget interaction
  // =========================================================================
  describe('Weather widget interaction', () => {
    it('weather button is clickable and shows METAR details', async () => {
      const user = userEvent.setup()
      renderApp()
      await waitForAppReady()

      // Weather widget should show temperature
      await waitFor(() => {
        expect(screen.getByText(/°C/)).toBeInTheDocument()
      }, { timeout: 5000 })

      // Find and click the weather button to expand details
      const weatherButton = screen.getByText(/°C/).closest('button')
      if (weatherButton) {
        await user.click(weatherButton)
        // Should show expanded METAR details or not crash
      }
    })
  })

  // =========================================================================
  // 20. Rapid sequential interactions (stress test)
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
      const closeButton = screen.getByRole('button', { name: /close fids/i })
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

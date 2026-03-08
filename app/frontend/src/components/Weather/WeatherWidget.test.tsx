import { describe, it, expect, vi, beforeEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { render, screen, waitFor, measureRenderTime, PERFORMANCE_THRESHOLDS } from '../../test/test-utils'
import WeatherWidget from './WeatherWidget'
import { server } from '../../test/mocks/server'
import { http, HttpResponse } from 'msw'

describe('WeatherWidget', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  describe('Loading state', () => {
    it('shows loading indicator initially', () => {
      render(<WeatherWidget />)
      expect(screen.getByText(/loading weather/i)).toBeInTheDocument()
    })
  })

  describe('Loaded state', () => {
    it('displays station code in expanded view', async () => {
      const user = userEvent.setup()
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.queryByText(/loading weather/i)).not.toBeInTheDocument()
      })

      // Expand to see station code
      const button = screen.getByRole('button')
      await user.click(button)

      await waitFor(() => {
        expect(screen.getByText('KSFO')).toBeInTheDocument()
      })
    })

    it('displays temperature', async () => {
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.getByText(/18°C/)).toBeInTheDocument()
      })
    })

    it('displays wind information', async () => {
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.getByText(/280@12kt/)).toBeInTheDocument()
      })
    })

    it('displays visibility', async () => {
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.getByText(/10SM/)).toBeInTheDocument()
      })
    })

    it('displays flight category indicator', async () => {
      render(<WeatherWidget />)

      await waitFor(() => {
        // VFR indicator (green dot)
        const indicator = document.querySelector('.bg-green-500')
        expect(indicator).toBeInTheDocument()
      })
    })
  })

  describe('Expanded state', () => {
    it('expands when clicked', async () => {
      const user = userEvent.setup()
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.queryByText(/loading weather/i)).not.toBeInTheDocument()
      })

      const button = screen.getByRole('button')
      await user.click(button)

      await waitFor(() => {
        expect(screen.getByText(/VFR - Clear/i)).toBeInTheDocument()
      })
    })

    it('shows detailed wind info when expanded', async () => {
      const user = userEvent.setup()
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.queryByText(/loading weather/i)).not.toBeInTheDocument()
      })

      const button = screen.getByRole('button')
      await user.click(button)

      await waitFor(() => {
        expect(screen.getAllByText(/wind/i).length).toBeGreaterThan(0)
      })
    })

    it('shows detailed visibility when expanded', async () => {
      const user = userEvent.setup()
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.queryByText(/loading weather/i)).not.toBeInTheDocument()
      })

      const button = screen.getByRole('button')
      await user.click(button)

      await waitFor(() => {
        expect(screen.getByText(/visibility/i)).toBeInTheDocument()
      })
    })

    it('shows cloud information when expanded', async () => {
      const user = userEvent.setup()
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.queryByText(/loading weather/i)).not.toBeInTheDocument()
      })

      const button = screen.getByRole('button')
      await user.click(button)

      await waitFor(() => {
        expect(screen.getByText(/clouds/i)).toBeInTheDocument()
      })
    })

    it('shows raw METAR when expanded', async () => {
      const user = userEvent.setup()
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.queryByText(/loading weather/i)).not.toBeInTheDocument()
      })

      const button = screen.getByRole('button')
      await user.click(button)

      await waitFor(() => {
        expect(screen.getByText(/raw metar/i)).toBeInTheDocument()
        expect(screen.getByText(/KSFO 281856Z 28012KT/)).toBeInTheDocument()
      })
    })

    it('collapses when clicked again', async () => {
      const user = userEvent.setup()
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.queryByText(/loading weather/i)).not.toBeInTheDocument()
      })

      const button = screen.getByRole('button')

      // Expand
      await user.click(button)
      await waitFor(() => {
        expect(screen.getByText(/raw metar/i)).toBeInTheDocument()
      })

      // Collapse
      await user.click(button)
      await waitFor(() => {
        expect(screen.queryByText(/raw metar/i)).not.toBeInTheDocument()
      })
    })
  })

  describe('Flight category colors', () => {
    it('shows green indicator for VFR', async () => {
      render(<WeatherWidget />)

      await waitFor(() => {
        const indicator = document.querySelector('.bg-green-500')
        expect(indicator).toBeInTheDocument()
      })
    })

    it('shows blue indicator for MVFR', async () => {
      server.use(
        http.get('/api/weather/current', () => {
          return HttpResponse.json({
            metar: {
              station: 'KSFO',
              observation_time: new Date().toISOString(),
              wind_direction: 280,
              wind_speed_kts: 12,
              wind_gust_kts: null,
              visibility_sm: 4,
              temperature_c: 15,
              dewpoint_c: 13,
              altimeter_inhg: 30.00,
              flight_category: 'MVFR',
              clouds: [{ coverage: 'BKN', altitude_ft: 2500 }],
              raw_metar: 'KSFO 281856Z 28012KT 4SM BKN025 15/13 A3000',
            },
            station: 'KSFO',
            timestamp: new Date().toISOString(),
          })
        })
      )

      render(<WeatherWidget />)

      await waitFor(() => {
        const indicator = document.querySelector('.bg-blue-500')
        expect(indicator).toBeInTheDocument()
      })
    })

    it('shows red indicator for IFR', async () => {
      server.use(
        http.get('/api/weather/current', () => {
          return HttpResponse.json({
            metar: {
              station: 'KSFO',
              observation_time: new Date().toISOString(),
              wind_direction: 280,
              wind_speed_kts: 15,
              wind_gust_kts: 25,
              visibility_sm: 2,
              temperature_c: 12,
              dewpoint_c: 11,
              altimeter_inhg: 29.92,
              flight_category: 'IFR',
              clouds: [{ coverage: 'OVC', altitude_ft: 800 }],
              raw_metar: 'KSFO 281856Z 28015G25KT 2SM OVC008 12/11 A2992',
            },
            station: 'KSFO',
            timestamp: new Date().toISOString(),
          })
        })
      )

      render(<WeatherWidget />)

      await waitFor(() => {
        const indicator = document.querySelector('.bg-red-500')
        expect(indicator).toBeInTheDocument()
      })
    })

    it('shows purple indicator for LIFR', async () => {
      server.use(
        http.get('/api/weather/current', () => {
          return HttpResponse.json({
            metar: {
              station: 'KSFO',
              observation_time: new Date().toISOString(),
              wind_direction: null,
              wind_speed_kts: 3,
              wind_gust_kts: null,
              visibility_sm: 0.5,
              temperature_c: 10,
              dewpoint_c: 10,
              altimeter_inhg: 29.85,
              flight_category: 'LIFR',
              clouds: [{ coverage: 'OVC', altitude_ft: 200 }],
              raw_metar: 'KSFO 281856Z VRB03KT 1/2SM FG OVC002 10/10 A2985',
            },
            station: 'KSFO',
            timestamp: new Date().toISOString(),
          })
        })
      )

      render(<WeatherWidget />)

      await waitFor(() => {
        const indicator = document.querySelector('.bg-purple-500')
        expect(indicator).toBeInTheDocument()
      })
    })
  })

  describe('Error state', () => {
    it('shows error message when API fails', async () => {
      server.use(
        http.get('/api/weather/current', () => {
          return HttpResponse.json({ error: 'Server error' }, { status: 500 })
        })
      )

      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.getByText(/weather unavailable/i)).toBeInTheDocument()
      })
    })

    it('shows error state with red background', async () => {
      server.use(
        http.get('/api/weather/current', () => {
          return HttpResponse.json({ error: 'Server error' }, { status: 500 })
        })
      )

      render(<WeatherWidget />)

      await waitFor(() => {
        const errorContainer = screen.getByText(/weather unavailable/i).closest('div')
        expect(errorContainer).toHaveClass('bg-red-900')
      })
    })
  })

  describe('Wind display', () => {
    it('shows gusts when present', async () => {
      server.use(
        http.get('/api/weather/current', () => {
          return HttpResponse.json({
            metar: {
              station: 'KSFO',
              observation_time: new Date().toISOString(),
              wind_direction: 270,
              wind_speed_kts: 15,
              wind_gust_kts: 25,
              visibility_sm: 10,
              temperature_c: 18,
              dewpoint_c: 12,
              altimeter_inhg: 30.05,
              flight_category: 'VFR',
              clouds: [],
              raw_metar: 'KSFO 281856Z 27015G25KT 10SM SKC 18/12 A3005',
            },
            station: 'KSFO',
            timestamp: new Date().toISOString(),
          })
        })
      )

      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.getByText(/270@15G25kt/)).toBeInTheDocument()
      })
    })

    it('shows VRB for variable winds', async () => {
      server.use(
        http.get('/api/weather/current', () => {
          return HttpResponse.json({
            metar: {
              station: 'KSFO',
              observation_time: new Date().toISOString(),
              wind_direction: null,
              wind_speed_kts: 5,
              wind_gust_kts: null,
              visibility_sm: 10,
              temperature_c: 18,
              dewpoint_c: 12,
              altimeter_inhg: 30.05,
              flight_category: 'VFR',
              clouds: [],
              raw_metar: 'KSFO 281856Z VRB05KT 10SM SKC 18/12 A3005',
            },
            station: 'KSFO',
            timestamp: new Date().toISOString(),
          })
        })
      )

      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.getByText(/VRB@5kt/)).toBeInTheDocument()
      })
    })
  })

  describe('Performance', () => {
    it('renders within performance threshold', async () => {
      const { time } = await measureRenderTime(() => render(<WeatherWidget />))
      expect(time).toBeLessThan(PERFORMANCE_THRESHOLDS.initialRender)
    })

    it('expand/collapse is performant', async () => {
      const user = userEvent.setup()
      render(<WeatherWidget />)

      await waitFor(() => {
        expect(screen.queryByText(/loading weather/i)).not.toBeInTheDocument()
      })

      const button = screen.getByRole('button')

      const start = performance.now()
      await user.click(button)
      await waitFor(() => {
        expect(screen.getByText(/raw metar/i)).toBeInTheDocument()
      })
      const elapsed = performance.now() - start

      expect(elapsed).toBeLessThan(PERFORMANCE_THRESHOLDS.interaction)
    })
  })
})

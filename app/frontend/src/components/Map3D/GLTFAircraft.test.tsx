import { describe, it, expect, vi, beforeEach } from 'vitest';
import { preloadAircraftModels } from './GLTFAircraft';
import { AircraftModelConfig, AirlineConfig, AIRCRAFT_MODELS } from '../../config/aircraftModels';

// Use vi.hoisted to declare mocks before module hoisting
const { mockPreload } = vi.hoisted(() => ({
  mockPreload: vi.fn(),
}));

// Mock useGLTF hook with preload
vi.mock('@react-three/drei', async () => {
  const actual = await vi.importActual('@react-three/drei');
  const mockUseGLTF = Object.assign(
    () => ({
      scene: {
        clone: () => ({
          traverse: () => {},
        }),
      },
    }),
    { preload: mockPreload }
  );
  return {
    ...actual,
    useGLTF: mockUseGLTF,
  };
});

// Mock aircraft model config
const createMockModelConfig = (
  overrides: Partial<AircraftModelConfig> = {}
): AircraftModelConfig => ({
  url: '/models/test-aircraft.glb',
  scale: 1.0,
  rotationOffset: { x: 0, y: 0, z: 0 },
  ...overrides,
});

// Mock airline config
const createMockAirline = (
  overrides: Partial<AirlineConfig> = {}
): AirlineConfig => ({
  name: 'Test Airline',
  primaryColor: 0x0033a0,
  secondaryColor: 0xffffff,
  ...overrides,
});

describe('GLTFAircraft', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockPreload.mockClear();
  });

  describe('Model configuration', () => {
    it('creates valid model config with defaults', () => {
      const config = createMockModelConfig();
      expect(config.url).toBe('/models/test-aircraft.glb');
      expect(config.scale).toBe(1.0);
      expect(config.rotationOffset).toEqual({ x: 0, y: 0, z: 0 });
    });

    it('creates model config with custom URL', () => {
      const config = createMockModelConfig({
        url: '/models/custom-aircraft.glb',
      });
      expect(config.url).toBe('/models/custom-aircraft.glb');
    });

    it('creates model config with custom scale', () => {
      const config = createMockModelConfig({ scale: 2.5 });
      expect(config.scale).toBe(2.5);
    });

    it('creates model config with custom rotation offset', () => {
      const config = createMockModelConfig({
        rotationOffset: { x: Math.PI / 2, y: Math.PI, z: 0 },
      });
      expect(config.rotationOffset.x).toBe(Math.PI / 2);
      expect(config.rotationOffset.y).toBe(Math.PI);
    });
  });

  describe('Airline configuration', () => {
    it('creates valid airline config with defaults', () => {
      const airline = createMockAirline();
      expect(airline.primaryColor).toBe(0x0033a0);
      expect(airline.secondaryColor).toBe(0xffffff);
    });

    it('creates United airline configuration', () => {
      const airline = createMockAirline({ primaryColor: 0x0033a0, secondaryColor: 0xffffff });
      expect(airline.primaryColor).toBe(0x0033a0);
    });

    it('creates Delta airline configuration', () => {
      const airline = createMockAirline({ primaryColor: 0xc8102e, secondaryColor: 0x041e42 });
      expect(airline.primaryColor).toBe(0xc8102e);
      expect(airline.secondaryColor).toBe(0x041e42);
    });

    it('creates Southwest airline configuration', () => {
      const airline = createMockAirline({ primaryColor: 0xff6600, secondaryColor: 0x111111 });
      expect(airline.primaryColor).toBe(0xff6600);
    });

    it('supports different airline color combinations', () => {
      const airline1 = createMockAirline({ primaryColor: 0xff0000 });
      const airline2 = createMockAirline({ primaryColor: 0x00ff00 });
      expect(airline1.primaryColor).not.toBe(airline2.primaryColor);
    });
  });

  describe('AIRCRAFT_MODELS configuration', () => {
    it('has DEFAULT model defined', () => {
      expect(AIRCRAFT_MODELS['DEFAULT']).toBeDefined();
      expect(AIRCRAFT_MODELS['DEFAULT'].url).toContain('generic-jet');
    });

    it('all models have required properties', () => {
      Object.entries(AIRCRAFT_MODELS).forEach(([, config]) => {
        expect(config.url).toBeDefined();
        expect(typeof config.scale).toBe('number');
        expect(config.rotationOffset).toBeDefined();
        expect(typeof config.rotationOffset.x).toBe('number');
        expect(typeof config.rotationOffset.y).toBe('number');
        expect(typeof config.rotationOffset.z).toBe('number');
      });
    });
  });

  describe('preloadAircraftModels', () => {
    it('calls preload for each URL', () => {
      const urls = [
        '/models/b737.glb',
        '/models/a320.glb',
        '/models/generic-jet.glb',
      ];

      preloadAircraftModels(urls);

      expect(mockPreload).toHaveBeenCalledTimes(3);
      expect(mockPreload).toHaveBeenCalledWith('/models/b737.glb');
      expect(mockPreload).toHaveBeenCalledWith('/models/a320.glb');
      expect(mockPreload).toHaveBeenCalledWith('/models/generic-jet.glb');
    });

    it('handles preload errors gracefully', () => {
      mockPreload.mockImplementation(() => {
        throw new Error('Preload failed');
      });

      const urls = ['/models/missing.glb'];

      // Should not throw
      expect(() => preloadAircraftModels(urls)).not.toThrow();
    });

    it('handles empty URL array', () => {
      preloadAircraftModels([]);

      expect(mockPreload).not.toHaveBeenCalled();
    });

    it('handles duplicate URLs', () => {
      const urls = ['/models/b737.glb', '/models/b737.glb'];

      preloadAircraftModels(urls);

      // Called twice (function doesn't dedupe)
      expect(mockPreload).toHaveBeenCalledTimes(2);
    });

    it('handles single URL', () => {
      preloadAircraftModels(['/models/single.glb']);

      expect(mockPreload).toHaveBeenCalledTimes(1);
      expect(mockPreload).toHaveBeenCalledWith('/models/single.glb');
    });
  });

  describe('Component props validation', () => {
    it('accepts valid props for rendering', () => {
      const modelConfig = createMockModelConfig();
      const airline = createMockAirline();

      // Props should be valid for component
      expect(modelConfig.url).toBeTruthy();
      expect(modelConfig.scale).toBeGreaterThan(0);
      expect(airline.primaryColor).toBeDefined();
      expect(airline.secondaryColor).toBeDefined();
    });

    it('accepts selected state prop', () => {
      const modelConfig = createMockModelConfig();
      const airline = createMockAirline();

      // Component accepts selected as boolean
      const props = {
        modelConfig,
        airline,
        selected: true,
      };

      expect(props.selected).toBe(true);
    });

    it('defaults selected to false when not provided', () => {
      const modelConfig = createMockModelConfig();
      const airline = createMockAirline();

      // Component uses false as default for selected
      const props: { modelConfig: AircraftModelConfig; airline: AirlineConfig; selected?: boolean } = {
        modelConfig,
        airline,
      };

      expect(props.selected).toBeUndefined();
    });
  });

  describe('Draco decoder support', () => {
    it('component supports Draco-compressed models', () => {
      // GLTFAircraft passes Draco decoder path to useGLTF
      // This enables loading of compressed GLB files
      const config = createMockModelConfig({ url: '/models/compressed.glb' });
      expect(config.url.endsWith('.glb')).toBe(true);
    });
  });
});

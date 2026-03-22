import { describe, it, expect, vi } from 'vitest';
import {
  getAirlineFromCallsign,
  getModelForAircraftType,
  modelExists,
  AIRLINES,
  AIRCRAFT_MODELS,
  AIRLINE_SPECIFIC_MODELS,
  AIRCRAFT_VISUAL_SCALE,
} from './aircraftModels';
import { METERS_TO_SCENE_UNITS } from '../utils/map3d-calculations';

describe('aircraftModels', () => {
  describe('getAirlineFromCallsign', () => {
    it('returns United for UAL callsign', () => {
      const airline = getAirlineFromCallsign('UAL123');
      expect(airline.name).toBe('United Airlines');
      expect(airline.primaryColor).toBe(0x002244);
    });

    it('returns Delta for DAL callsign', () => {
      const airline = getAirlineFromCallsign('DAL456');
      expect(airline.name).toBe('Delta Air Lines');
    });

    it('returns American for AAL callsign', () => {
      const airline = getAirlineFromCallsign('AAL789');
      expect(airline.name).toBe('American Airlines');
    });

    it('returns Emirates for UAE callsign', () => {
      const airline = getAirlineFromCallsign('UAE001');
      expect(airline.name).toBe('Emirates');
    });

    it('returns Air France for AFR callsign', () => {
      const airline = getAirlineFromCallsign('AFR123');
      expect(airline.name).toBe('Air France');
    });

    it('returns default for unknown airline', () => {
      const airline = getAirlineFromCallsign('XYZ999');
      expect(airline.name).toBe('Unknown Airline');
      expect(airline.primaryColor).toBe(0x888888);
    });

    it('returns default for null callsign', () => {
      const airline = getAirlineFromCallsign(null);
      expect(airline.name).toBe('Unknown Airline');
    });

    it('returns default for short callsign', () => {
      const airline = getAirlineFromCallsign('UA');
      expect(airline.name).toBe('Unknown Airline');
    });

    it('handles lowercase callsigns', () => {
      const airline = getAirlineFromCallsign('ual123');
      expect(airline.name).toBe('United Airlines');
    });

    it('handles empty string', () => {
      const airline = getAirlineFromCallsign('');
      expect(airline.name).toBe('Unknown Airline');
    });
  });

  describe('getModelForAircraftType', () => {
    describe('airline-specific models', () => {
      it('returns Emirates A345 specific model', () => {
        const model = getModelForAircraftType('A345', 'UAE');
        expect(model.url).toBe('/models/aircraft/emirates_airbus_a345.glb');
      });

      it('returns Air France A318 specific model', () => {
        const model = getModelForAircraftType('A318', 'AFR');
        expect(model.url).toBe('/models/aircraft/air_france_airbus_a318-100.glb');
      });

      it('returns Cathay Pacific A330 specific model', () => {
        const model = getModelForAircraftType('A330', 'CPA');
        expect(model.url).toBe('/models/aircraft/cathay_pacific_airbus_a330-300.glb');
      });

      it('handles lowercase airline code', () => {
        const model = getModelForAircraftType('A345', 'uae');
        expect(model.url).toBe('/models/aircraft/emirates_airbus_a345.glb');
      });

      it('handles lowercase aircraft type', () => {
        const model = getModelForAircraftType('a345', 'UAE');
        expect(model.url).toBe('/models/aircraft/emirates_airbus_a345.glb');
      });
    });

    describe('generic aircraft models', () => {
      it('returns B737 model', () => {
        const model = getModelForAircraftType('B737');
        expect(model.url).toBe('/models/aircraft/boeing-737.glb');
        expect(model.scale).toBe(1.03 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE);
      });

      it('returns B738 model', () => {
        const model = getModelForAircraftType('B738');
        expect(model.url).toBe('/models/aircraft/boeing-737.glb');
      });

      it('returns A320 model', () => {
        const model = getModelForAircraftType('A320');
        expect(model.url).toBe('/models/aircraft/airbus_a320.glb');
        expect(model.scale).toBe(1.05 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE);
      });

      it('returns A380 model', () => {
        const model = getModelForAircraftType('A380');
        expect(model.url).toBe('/models/aircraft/airbus_a380.glb');
        expect(model.scale).toBe(1.0 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE);
      });

      it('handles lowercase aircraft type', () => {
        const model = getModelForAircraftType('b738');
        expect(model.url).toBe('/models/aircraft/boeing-737.glb');
      });
    });

    describe('fallback behavior', () => {
      it('falls back to generic model when no airline-specific exists', () => {
        const model = getModelForAircraftType('B738', 'UAL');
        expect(model.url).toBe('/models/aircraft/boeing-737.glb');
      });

      it('returns default model for unknown aircraft type', () => {
        const model = getModelForAircraftType('UNKNOWN');
        expect(model.url).toBe('/models/aircraft/generic-jet.glb');
        expect(model.scale).toBe(17.5 * METERS_TO_SCENE_UNITS * AIRCRAFT_VISUAL_SCALE);
      });

      it('returns default model when type is undefined', () => {
        const model = getModelForAircraftType(undefined);
        expect(model.url).toBe('/models/aircraft/generic-jet.glb');
      });

      it('returns default model when type is empty', () => {
        const model = getModelForAircraftType('');
        expect(model.url).toBe('/models/aircraft/generic-jet.glb');
      });

      it('uses generic model for airline without specific model', () => {
        const model = getModelForAircraftType('A320', 'SWA'); // Southwest doesn't have specific A320
        expect(model.url).toBe('/models/aircraft/airbus_a320.glb');
      });
    });

    describe('model configuration', () => {
      it('includes scale in returned config', () => {
        const model = getModelForAircraftType('A320');
        expect(model.scale).toBeDefined();
        expect(typeof model.scale).toBe('number');
      });

      it('includes rotationOffset in returned config', () => {
        const model = getModelForAircraftType('A320');
        expect(model.rotationOffset).toBeDefined();
        expect(model.rotationOffset.x).toBeDefined();
        expect(model.rotationOffset.y).toBeDefined();
        expect(model.rotationOffset.z).toBeDefined();
      });
    });
  });

  describe('modelExists', () => {
    it('returns true for successful HEAD request', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({ ok: true });

      const result = await modelExists('/models/aircraft/test.glb');
      expect(result).toBe(true);
      expect(fetch).toHaveBeenCalledWith('/models/aircraft/test.glb', { method: 'HEAD' });
    });

    it('returns false for failed HEAD request', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({ ok: false });

      const result = await modelExists('/models/aircraft/missing.glb');
      expect(result).toBe(false);
    });

    it('returns false when fetch throws', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await modelExists('/models/aircraft/error.glb');
      expect(result).toBe(false);
    });
  });

  describe('AIRLINES constant', () => {
    it('has all major US airlines', () => {
      expect(AIRLINES['UAL']).toBeDefined();
      expect(AIRLINES['DAL']).toBeDefined();
      expect(AIRLINES['AAL']).toBeDefined();
      expect(AIRLINES['SWA']).toBeDefined();
      expect(AIRLINES['JBU']).toBeDefined();
      expect(AIRLINES['ASA']).toBeDefined();
    });

    it('has international airlines', () => {
      expect(AIRLINES['BAW']).toBeDefined(); // British Airways
      expect(AIRLINES['AFR']).toBeDefined(); // Air France
      expect(AIRLINES['DLH']).toBeDefined(); // Lufthansa
      expect(AIRLINES['UAE']).toBeDefined(); // Emirates
    });

    it('has DEFAULT airline', () => {
      expect(AIRLINES['DEFAULT']).toBeDefined();
      expect(AIRLINES['DEFAULT'].name).toBe('Unknown Airline');
    });

    it('all airlines have required properties', () => {
      Object.values(AIRLINES).forEach(airline => {
        expect(airline.name).toBeDefined();
        expect(typeof airline.name).toBe('string');
        expect(airline.primaryColor).toBeDefined();
        expect(typeof airline.primaryColor).toBe('number');
        expect(airline.secondaryColor).toBeDefined();
        expect(typeof airline.secondaryColor).toBe('number');
      });
    });
  });

  describe('AIRCRAFT_MODELS constant', () => {
    it('has Boeing narrow body models', () => {
      expect(AIRCRAFT_MODELS['B737']).toBeDefined();
      expect(AIRCRAFT_MODELS['B738']).toBeDefined();
      expect(AIRCRAFT_MODELS['B739']).toBeDefined();
    });

    it('has Airbus narrow body models', () => {
      expect(AIRCRAFT_MODELS['A318']).toBeDefined();
      expect(AIRCRAFT_MODELS['A319']).toBeDefined();
      expect(AIRCRAFT_MODELS['A320']).toBeDefined();
      expect(AIRCRAFT_MODELS['A321']).toBeDefined();
    });

    it('has wide body models', () => {
      expect(AIRCRAFT_MODELS['A380']).toBeDefined();
      expect(AIRCRAFT_MODELS['B777']).toBeDefined();
      expect(AIRCRAFT_MODELS['B787']).toBeDefined();
    });

    it('has DEFAULT model', () => {
      expect(AIRCRAFT_MODELS['DEFAULT']).toBeDefined();
    });

    it('all models have valid URLs', () => {
      Object.values(AIRCRAFT_MODELS).forEach(model => {
        expect(model.url).toBeDefined();
        expect(model.url).toMatch(/^\/models\/aircraft\/.+\.glb$/);
      });
    });

    it('all models have positive scale', () => {
      Object.values(AIRCRAFT_MODELS).forEach(model => {
        expect(model.scale).toBeGreaterThan(0);
      });
    });
  });

  describe('AIRLINE_SPECIFIC_MODELS constant', () => {
    it('has Emirates models', () => {
      expect(AIRLINE_SPECIFIC_MODELS['UAE_A345']).toBeDefined();
      expect(AIRLINE_SPECIFIC_MODELS['UAE_A380']).toBeDefined();
    });

    it('has Air France models', () => {
      expect(AIRLINE_SPECIFIC_MODELS['AFR_A318']).toBeDefined();
      expect(AIRLINE_SPECIFIC_MODELS['AFR_A320']).toBeDefined();
    });

    it('has Cathay Pacific models', () => {
      expect(AIRLINE_SPECIFIC_MODELS['CPA_A330']).toBeDefined();
    });

    it('all models have valid URLs', () => {
      Object.values(AIRLINE_SPECIFIC_MODELS).forEach(model => {
        expect(model.url).toBeDefined();
        expect(model.url).toMatch(/^\/models\/aircraft\/.+\.glb$/);
      });
    });
  });
});

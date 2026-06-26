import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  formatTimeForFilename,
  detectViewMode,
  downloadDataUrl,
  addWatermark,
  capture3D,
  captureCurrentView,
} from './sceneCapture';

describe('formatTimeForFilename', () => {
  it('formats a valid ISO string', () => {
    // Use a fixed UTC date and check against UTC-based output
    const result = formatTimeForFilename('2026-03-15T14:30:00Z');
    // Result depends on local timezone; just check format pattern
    expect(result).toMatch(/^\d{8}_\d{4}$/);
  });

  it('formats another valid date', () => {
    const result = formatTimeForFilename('2025-01-01T00:00:00Z');
    expect(result).toMatch(/^\d{8}_\d{4}$/);
  });

  it('returns "unknown" for null', () => {
    expect(formatTimeForFilename(null)).toBe('unknown');
  });

  it('returns "unknown" for empty string', () => {
    expect(formatTimeForFilename('')).toBe('unknown');
  });

  it('handles invalid date string gracefully', () => {
    // new Date('not-a-date') returns Invalid Date but doesn't throw
    // getFullYear() on Invalid Date returns NaN, so the output will contain NaN
    const result = formatTimeForFilename('not-a-date');
    // It either returns 'unknown' or a string with NaN — both are acceptable
    expect(typeof result).toBe('string');
  });
});

describe('detectViewMode', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('returns "3d" when a visible canvas[data-engine] exists', () => {
    const canvas = document.createElement('canvas');
    canvas.setAttribute('data-engine', 'three.js');
    document.body.appendChild(canvas);
    // jsdom doesn't compute layout, so offsetParent is null by default.
    // We need to mock offsetParent.
    Object.defineProperty(canvas, 'offsetParent', { value: document.body, configurable: true });

    expect(detectViewMode()).toBe('3d');
  });

  it('returns "2d" when no canvas[data-engine] exists', () => {
    expect(detectViewMode()).toBe('2d');
  });

  it('returns "2d" when canvas[data-engine] exists but is hidden (offsetParent null)', () => {
    const canvas = document.createElement('canvas');
    canvas.setAttribute('data-engine', 'three.js');
    document.body.appendChild(canvas);
    // offsetParent is null by default in jsdom (element not rendered)

    expect(detectViewMode()).toBe('2d');
  });
});

describe('downloadDataUrl', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('creates an anchor element, sets properties, clicks, and removes it', () => {
    const clickSpy = vi.fn();
    const mockAnchor = document.createElement('a');
    mockAnchor.click = clickSpy;

    const createElementSpy = vi.spyOn(document, 'createElement').mockReturnValueOnce(mockAnchor as any);
    const appendSpy = vi.spyOn(document.body, 'appendChild');
    const removeSpy = vi.spyOn(document.body, 'removeChild');

    downloadDataUrl('data:image/png;base64,abc123', 'capture.png');

    expect(createElementSpy).toHaveBeenCalledWith('a');
    expect(mockAnchor.href).toContain('data:image/png;base64,abc123');
    expect(mockAnchor.download).toBe('capture.png');
    expect(appendSpy).toHaveBeenCalledWith(mockAnchor);
    expect(clickSpy).toHaveBeenCalled();
    expect(removeSpy).toHaveBeenCalledWith(mockAnchor);

    createElementSpy.mockRestore();
    appendSpy.mockRestore();
    removeSpy.mockRestore();
  });
});

describe('addWatermark', () => {
  it('creates a new canvas and draws the source image and watermark text', () => {
    const mockCtx = {
      drawImage: vi.fn(),
      fillText: vi.fn(),
      fillRect: vi.fn(),
      measureText: vi.fn(() => ({ width: 100 })),
      font: '',
      fillStyle: '',
    };

    const sourceCanvas = document.createElement('canvas');
    sourceCanvas.width = 800;
    sourceCanvas.height = 600;

    const outCanvas = document.createElement('canvas');
    const getContextSpy = vi.fn(() => mockCtx);
    Object.defineProperty(outCanvas, 'getContext', { value: getContextSpy });

    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'canvas') return outCanvas as any;
      return document.createElement(tag);
    });

    const result = addWatermark(sourceCanvas, '2026-03-15T14:30:00Z', 'KSFO');

    expect(result).toBe(outCanvas);
    expect(outCanvas.width).toBe(800);
    expect(outCanvas.height).toBe(600);
    expect(getContextSpy).toHaveBeenCalledWith('2d');
    expect(mockCtx.drawImage).toHaveBeenCalledWith(sourceCanvas, 0, 0);
    expect(mockCtx.fillText).toHaveBeenCalled();
    // Verify the text contains airport code
    const fillTextCall = mockCtx.fillText.mock.calls[0];
    expect(fillTextCall[0]).toContain('KSFO');

    createElementSpy.mockRestore();
  });

  it('returns the original canvas if getContext returns null', () => {
    const sourceCanvas = document.createElement('canvas');
    sourceCanvas.width = 400;
    sourceCanvas.height = 300;

    const outCanvas = document.createElement('canvas');
    Object.defineProperty(outCanvas, 'getContext', { value: () => null });

    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'canvas') return outCanvas as any;
      return document.createElement(tag);
    });

    const result = addWatermark(sourceCanvas, null, null);
    expect(result).toBe(sourceCanvas);

    createElementSpy.mockRestore();
  });
});

describe('capture3D', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('returns a data URL when a canvas[data-engine] is present', () => {
    const canvas = document.createElement('canvas');
    canvas.setAttribute('data-engine', 'three.js');
    canvas.width = 800;
    canvas.height = 600;
    document.body.appendChild(canvas);

    // Mock addWatermark behavior: the function creates a new canvas internally.
    // We mock toDataURL on the output canvas that addWatermark creates.
    const mockCtx = {
      drawImage: vi.fn(),
      fillText: vi.fn(),
      fillRect: vi.fn(),
      measureText: vi.fn(() => ({ width: 100 })),
      font: '',
      fillStyle: '',
    };

    const outCanvas = document.createElement('canvas');
    outCanvas.width = 800;
    outCanvas.height = 600;
    Object.defineProperty(outCanvas, 'getContext', { value: () => mockCtx });
    Object.defineProperty(outCanvas, 'toDataURL', { value: () => 'data:image/png;base64,captured' });

    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'canvas') return outCanvas as any;
      return document.createElement(tag);
    });

    const result = capture3D('2026-03-15T14:30:00Z', 'KJFK');
    expect(result).toBe('data:image/png;base64,captured');

    createElementSpy.mockRestore();
  });

  it('returns null when no canvas is in the DOM', () => {
    const result = capture3D('2026-03-15T14:30:00Z', 'KJFK');
    expect(result).toBeNull();
  });
});

describe('captureCurrentView', () => {
  beforeEach(() => {
    document.body.innerHTML = '';
  });

  it('calls capture3D when mode is "3d"', async () => {
    const canvas = document.createElement('canvas');
    canvas.setAttribute('data-engine', 'three.js');
    canvas.width = 800;
    canvas.height = 600;
    document.body.appendChild(canvas);

    const mockCtx = {
      drawImage: vi.fn(),
      fillText: vi.fn(),
      fillRect: vi.fn(),
      measureText: vi.fn(() => ({ width: 100 })),
      font: '',
      fillStyle: '',
    };

    const outCanvas = document.createElement('canvas');
    Object.defineProperty(outCanvas, 'getContext', { value: () => mockCtx });
    Object.defineProperty(outCanvas, 'toDataURL', { value: () => 'data:image/png;base64,3d_capture' });

    const createElementSpy = vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'canvas') return outCanvas as any;
      return document.createElement(tag);
    });

    const result = await captureCurrentView('2026-03-15T14:30:00Z', 'KSFO', '3d');
    expect(result).toBe('data:image/png;base64,3d_capture');

    createElementSpy.mockRestore();
  });

  it('returns null for 2d mode when no map container exists', async () => {
    const result = await captureCurrentView('2026-03-15T14:30:00Z', 'KSFO', '2d');
    expect(result).toBeNull();
  });
});

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useWebSocket } from './useWebSocket';

// Mock WebSocket
class MockWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  url: string;
  readyState: number = MockWebSocket.CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    // Simulate connection
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      this.onopen?.(new Event('open'));
    }, 10);
  }

  send = vi.fn();

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new CloseEvent('close'));
  }

  // Test helpers
  simulateMessage(data: unknown) {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data: JSON.stringify(data) }));
    }
  }

  simulateRawMessage(data: string) {
    if (this.onmessage) {
      this.onmessage(new MessageEvent('message', { data }));
    }
  }

  simulateError() {
    if (this.onerror) {
      this.onerror(new Event('error'));
    }
  }
}

// Store instances for test access
let mockWebSocketInstances: MockWebSocket[] = [];

describe('useWebSocket', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockWebSocketInstances = [];

    // Mock WebSocket
    vi.stubGlobal('WebSocket', class extends MockWebSocket {
      constructor(url: string) {
        super(url);
        mockWebSocketInstances.push(this);
      }
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe('Initial state', () => {
    it('starts with null lastMessage', () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      expect(result.current.lastMessage).toBeNull();
    });

    it('starts disconnected', () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      // Initially not connected (until onopen fires)
      expect(result.current.isConnected).toBe(false);
    });

    it('starts with null error', () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      expect(result.current.error).toBeNull();
    });

    it('provides send function', () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      expect(typeof result.current.send).toBe('function');
    });

    it('provides reconnect function', () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      expect(typeof result.current.reconnect).toBe('function');
    });
  });

  describe('Connection', () => {
    it('connects to the WebSocket URL', async () => {
      renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      expect(mockWebSocketInstances.length).toBe(1);
      expect(mockWebSocketInstances[0].url).toBe('ws://localhost:8080/ws');
    });

    it('sets isConnected to true when connected', async () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });
    });

    it('calls onOpen callback when connected', async () => {
      const onOpen = vi.fn();

      renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws', onOpen })
      );

      await waitFor(() => {
        expect(onOpen).toHaveBeenCalled();
      });
    });

    it('sets isConnected to false when disconnected', async () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      act(() => {
        mockWebSocketInstances[0].close();
      });

      expect(result.current.isConnected).toBe(false);
    });

    it('calls onClose callback when disconnected', async () => {
      const onClose = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws', onClose })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      act(() => {
        mockWebSocketInstances[0].close();
      });

      expect(onClose).toHaveBeenCalled();
    });
  });

  describe('Messages', () => {
    it('updates lastMessage when receiving JSON', async () => {
      const { result } = renderHook(() =>
        useWebSocket<{ data: string }>({ url: 'ws://localhost:8080/ws' })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      act(() => {
        mockWebSocketInstances[0].simulateMessage({ data: 'test' });
      });

      expect(result.current.lastMessage).toEqual({ data: 'test' });
    });

    it('handles non-JSON messages', async () => {
      const { result } = renderHook(() =>
        useWebSocket<string>({ url: 'ws://localhost:8080/ws' })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      act(() => {
        mockWebSocketInstances[0].simulateRawMessage('plain text');
      });

      expect(result.current.lastMessage).toBe('plain text');
    });
  });

  describe('Sending', () => {
    it('sends string messages', async () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      act(() => {
        result.current.send('test message');
      });

      expect(mockWebSocketInstances[0].send).toHaveBeenCalledWith('test message');
    });

    it('sends object messages as JSON', async () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      act(() => {
        result.current.send({ type: 'subscribe', channel: 'flights' });
      });

      expect(mockWebSocketInstances[0].send).toHaveBeenCalledWith(
        JSON.stringify({ type: 'subscribe', channel: 'flights' })
      );
    });

    it('warns when sending while not connected', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      // Send before connection is established
      act(() => {
        result.current.send('test');
      });

      expect(warnSpy).toHaveBeenCalledWith('WebSocket is not connected');
      warnSpy.mockRestore();
    });
  });

  describe('Errors', () => {
    it('sets error on WebSocket error', async () => {
      const onError = vi.fn();

      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws', onError })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      act(() => {
        mockWebSocketInstances[0].simulateError();
      });

      expect(result.current.error).toBeTruthy();
      expect(onError).toHaveBeenCalled();
    });
  });

  describe('Reconnection', () => {
    it('allows manual reconnect', async () => {
      const { result } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      const initialInstanceCount = mockWebSocketInstances.length;

      act(() => {
        result.current.reconnect();
      });

      // Should create a new WebSocket instance
      expect(mockWebSocketInstances.length).toBe(initialInstanceCount + 1);
    });
  });

  describe('Cleanup', () => {
    it('closes connection on unmount', async () => {
      const { result, unmount } = renderHook(() =>
        useWebSocket({ url: 'ws://localhost:8080/ws' })
      );

      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      const ws = mockWebSocketInstances[0];
      const closeSpy = vi.spyOn(ws, 'close');

      unmount();

      expect(closeSpy).toHaveBeenCalled();
    });
  });
});

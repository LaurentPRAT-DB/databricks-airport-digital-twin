import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import React from 'react';
import { ConnectionStatus } from './ConnectionStatus';

describe('ConnectionStatus', () => {
  let originalOnLine: PropertyDescriptor | undefined;

  afterEach(() => {
    // Restore navigator.onLine
    if (originalOnLine) {
      Object.defineProperty(navigator, 'onLine', originalOnLine);
    }
  });

  function setOnlineStatus(online: boolean) {
    originalOnLine = Object.getOwnPropertyDescriptor(navigator, 'onLine');
    Object.defineProperty(navigator, 'onLine', { value: online, configurable: true });
  }

  it('renders nothing when online', () => {
    setOnlineStatus(true);
    const { container } = render(<ConnectionStatus />);
    expect(container.firstChild).toBeNull();
  });

  it('renders offline banner when offline', () => {
    setOnlineStatus(false);
    render(<ConnectionStatus />);
    expect(screen.getByText(/offline/i)).toBeInTheDocument();
    expect(screen.getByText(/reconnecting/i)).toBeInTheDocument();
  });

  it('shows banner when going offline', () => {
    setOnlineStatus(true);
    render(<ConnectionStatus />);
    expect(screen.queryByText(/offline/i)).toBeNull();

    // Simulate going offline
    act(() => {
      Object.defineProperty(navigator, 'onLine', { value: false, configurable: true });
      window.dispatchEvent(new Event('offline'));
    });

    expect(screen.getByText(/offline/i)).toBeInTheDocument();
  });

  it('hides banner when coming back online', () => {
    setOnlineStatus(false);
    render(<ConnectionStatus />);
    expect(screen.getByText(/offline/i)).toBeInTheDocument();

    // Simulate coming online
    act(() => {
      Object.defineProperty(navigator, 'onLine', { value: true, configurable: true });
      window.dispatchEvent(new Event('online'));
    });

    expect(screen.queryByText(/offline/i)).toBeNull();
  });
});

import { createContext, useContext, useState, useEffect, useCallback, type ReactNode } from 'react';

interface ThemeContextValue {
  isDark: boolean;
  toggle: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({ isDark: false, toggle: () => {} });

function getInitialTheme(): boolean {
  try {
    const stored = localStorage.getItem('theme');
    if (stored === 'dark') return true;
    if (stored === 'light') return false;
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  } catch {
    return false;
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [isDark, setIsDark] = useState(getInitialTheme);

  useEffect(() => {
    const root = document.documentElement;
    if (isDark) {
      root.classList.add('dark');
    } else {
      root.classList.remove('dark');
    }
    try { localStorage.setItem('theme', isDark ? 'dark' : 'light'); } catch { /* noop */ }
  }, [isDark]);

  const toggle = useCallback(() => setIsDark((prev) => !prev), []);

  return (
    <ThemeContext.Provider value={{ isDark, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}

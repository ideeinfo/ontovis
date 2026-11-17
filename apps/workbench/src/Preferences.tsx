import { createContext, useContext, useEffect, useLayoutEffect, useState, type ReactNode } from 'react';
import { translate, type Locale, type MessageKey } from './messages';
type Theme = 'light' | 'dark' | 'system';
function preference(key: string, allowed: readonly string[], fallback: string) {
  try { const value = localStorage.getItem(key); return value && allowed.includes(value) ? value : fallback; }
  catch { return fallback; }
}
const Preferences = createContext({locale:'zh' as Locale, theme:'system' as Theme, resolved:'light',
  setLocale:(_value: Locale) => {}, setTheme:(_value: Theme) => {},
  t:(key: MessageKey, values?: Record<string, string | number>) => translate('zh', key, values)});
export function PreferencesProvider({children}: {children: ReactNode}) {
  const [locale, setLocale] = useState(() => preference('ontovis.locale', ['zh','en'], 'zh') as Locale);
  const [theme, setTheme] = useState(() => preference('ontovis.theme', ['light','dark','system'], 'system') as Theme);
  const [dark, setDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches);
  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const update = () => setDark(media.matches); media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  const resolved = theme === 'system' ? (dark ? 'dark' : 'light') : theme;
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = resolved;
    document.documentElement.lang = locale === 'zh' ? 'zh-CN' : 'en';
    document.documentElement.style.colorScheme = resolved;
    try { localStorage.setItem('ontovis.locale', locale); localStorage.setItem('ontovis.theme', theme); } catch { /* Preferences are optional. */ }
  }, [locale, theme, resolved]);
  return <Preferences.Provider value={{locale, theme, resolved, setLocale, setTheme,
    t:(key, values) => translate(locale, key, values)}}>{children}</Preferences.Provider>;
}
export function usePreferences() { return useContext(Preferences); }

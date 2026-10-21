import { createRoot } from 'react-dom/client';
import { Workbench } from './Workbench';
import { PreferencesProvider } from './Preferences';
import './design.css';
import './theme.css';
import './workbench.css';
import './compact.css';
import './navigation.css';
createRoot(document.getElementById('root')!).render(<PreferencesProvider><Workbench /></PreferencesProvider>);

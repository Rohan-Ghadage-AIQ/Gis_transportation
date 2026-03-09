
import '@maptiler/sdk/dist/maptiler-sdk.css';
import { BrowserRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { UploadPage } from './pages/UploadPage';
import { ResultsPage } from './pages/ResultsPage';
import { MaintenanceUploadPage } from './pages/MaintenanceUploadPage';
import { MaintenanceResultsPage } from './pages/MaintenanceResultsPage';

/* ── Module Toggle Bar ── */
const ModuleToggle = () => {
    const navigate = useNavigate();
    const location = useLocation();
    const isMaintenance = location.pathname.startsWith('/maintenance');

    return (
        <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            gap: 0, padding: '6px 8px',
            background: 'var(--surface)', borderBottom: '1px solid var(--border)',
        }}>
            <button
                onClick={() => navigate('/')}
                style={{
                    padding: '7px 22px', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                    border: '1.5px solid var(--primary)',
                    borderRight: 'none',
                    borderRadius: '8px 0 0 8px',
                    background: !isMaintenance ? 'var(--primary)' : 'transparent',
                    color: !isMaintenance ? '#fff' : 'var(--primary)',
                    transition: 'all 0.2s',
                }}
            >
                🚚 AIQ Logistics
            </button>
            <button
                onClick={() => navigate('/maintenance')}
                style={{
                    padding: '7px 22px', fontSize: 13, fontWeight: 700, cursor: 'pointer',
                    border: '1.5px solid var(--primary)',
                    borderRadius: '0 8px 8px 0',
                    background: isMaintenance ? 'var(--primary)' : 'transparent',
                    color: isMaintenance ? '#fff' : 'var(--primary)',
                    transition: 'all 0.2s',
                }}
            >
                🔧 AIQ Maintenance Team
            </button>
        </div>
    );
};

function App() {
    return (
        <BrowserRouter>
            <ModuleToggle />
            <Routes>
                {/* Logistics (unchanged) */}
                <Route path="/" element={<UploadPage />} />
                <Route path="/results" element={<ResultsPage />} />
                {/* Maintenance (new) */}
                <Route path="/maintenance" element={<MaintenanceUploadPage />} />
                <Route path="/maintenance-results" element={<MaintenanceResultsPage />} />
            </Routes>
        </BrowserRouter>
    );
}

export default App;

import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/api';
import { MapView } from '../components/MapView';
import { StatsPanel } from '../components/StatsPanel';
import { ChatWidget } from '../components/ChatWidget';
import type { RouteResults } from '../types/api';

// Gemini sparkle icon
const GeminiIcon = ({ size = 16 }: { size?: number }) => (
    <svg width={size} height={size} viewBox="0 0 28 28" fill="none">
        <path d="M14 0C14 7.732 7.732 14 0 14C7.732 14 14 20.268 14 28C14 20.268 20.268 14 28 14C20.268 14 14 7.732 14 0Z" fill="currentColor" />
    </svg>
);

export const ResultsPage: React.FC = () => {
    const navigate = useNavigate();
    const [results, setResults] = useState<RouteResults | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [error, setError] = useState<string>('');
    const [notification, setNotification] = useState<{ message: string; type: 'success' | 'warning' } | null>(null);
    const [chatOpen, setChatOpen] = useState(false);

    useEffect(() => {
        const fetchResults = async () => {
            try {
                const data = await apiService.getResults();
                setResults(data);
                setError('');
            } catch (err: any) {
                setError(err.response?.data?.detail || 'Failed to load results');
                if (err.response?.status === 400) {
                    setTimeout(() => navigate('/'), 2000);
                }
            } finally {
                setIsLoading(false);
            }
        };
        fetchResults();
    }, [navigate]);

    const handleRefreshTraffic = async () => {
        setIsRefreshing(true);
        setNotification(null);
        try {
            const data = await apiService.refreshTraffic();
            setResults(data);

            if (data.rerouted_vehicles && data.rerouted_vehicles.length > 0) {
                const isWeather = data.weather_rerouted;
                setNotification({
                    message: isWeather
                        ? `⛈️ Weather alert: ${data.rerouted_vehicles.length} vehicle(s) rerouted to avoid waterlogging zones.`
                        : `Traffic update: ${data.rerouted_vehicles.length} vehicles rerouted for better efficiency.`,
                    type: 'warning'
                });
            } else if (data.weather_alerts && data.weather_alerts.length > 0) {
                setNotification({
                    message: `🌧️ Rain detected at ${data.weather_alerts.length} station(s), but current routes remain optimal.`,
                    type: 'success'
                });
            } else {
                setNotification({
                    message: "Traffic data updated. Current routes remain optimal.",
                    type: 'success'
                });
            }
            setTimeout(() => setNotification(null), 5000);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Failed to refresh traffic');
        } finally {
            setIsRefreshing(false);
        }
    };

    if (isLoading) {
        return (
            <div style={{
                minHeight: '100vh', background: 'var(--bg)',
                display: 'flex', alignItems: 'center', justifyContent: 'center'
            }}>
                <div style={{ textAlign: 'center' }}>
                    <div className="spinner" style={{ margin: '0 auto 16px' }}></div>
                    <p style={{ color: 'var(--text-muted)', fontSize: 16 }}>Loading results...</p>
                </div>
            </div>
        );
    }

    if (error || !results) {
        return (
            <div style={{
                minHeight: '100vh', background: 'var(--bg)',
                display: 'flex', alignItems: 'center', justifyContent: 'center'
            }}>
                <div style={{ textAlign: 'center' }}>
                    <div style={{
                        width: 56, height: 56, borderRadius: '50%', margin: '0 auto 16px',
                        background: 'var(--danger-light)', display: 'flex',
                        alignItems: 'center', justifyContent: 'center', fontSize: 28
                    }}>⚠</div>
                    <p style={{ color: 'var(--text)', fontSize: 16, marginBottom: 4 }}>{error}</p>
                    <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>Redirecting to upload page...</p>
                </div>
            </div>
        );
    }

    return (
        <div style={{
            height: '100vh', display: 'flex', flexDirection: 'column',
            background: 'var(--bg)', overflow: 'hidden', position: 'relative'
        }}>
            {/* Notification Toast */}
            {notification && (
                <div style={{
                    position: 'fixed', top: 72, right: 24, zIndex: 50,
                    padding: '12px 20px', borderRadius: 10,
                    display: 'flex', alignItems: 'center', gap: 10,
                    boxShadow: 'var(--shadow-lg)', fontWeight: 600, fontSize: 14,
                    animation: 'slideIn 0.3s ease-out',
                    ...(notification.type === 'warning'
                        ? { background: 'var(--warning)', color: '#fff' }
                        : { background: 'var(--success)', color: '#fff' })
                }}>
                    <span style={{ fontSize: 18 }}>{notification.type === 'warning' ? '🔄' : '✓'}</span>
                    {notification.message}
                </div>
            )}

            {/* Header */}
            <div style={{
                padding: '12px 24px', display: 'flex',
                alignItems: 'center', justifyContent: 'space-between',
                borderBottom: '1px solid var(--border)',
                background: 'var(--bg)',
            }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: 'var(--text)' }}>
                        Optimized Vehicle Routes
                    </h1>
                    <p style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
                        {results.summary.total_fleets} vehicles · {results.summary.total_parcels} deliveries
                    </p>
                </div>
                <div style={{ display: 'flex', gap: 10 }}>
                    {/* Gemini AI Chatbot Button */}
                    <button
                        onClick={() => setChatOpen(!chatOpen)}
                        className="gemini-btn"
                        style={{
                            background: chatOpen
                                ? 'linear-gradient(135deg, #6d28d9, #5b21b6)'
                                : 'linear-gradient(135deg, #7c3aed, #6d28d9)',
                            color: '#fff',
                            border: 'none',
                            borderRadius: 8,
                            padding: '8px 16px',
                            fontWeight: 600,
                            cursor: 'pointer',
                            fontSize: 13,
                            display: 'flex',
                            alignItems: 'center',
                            gap: 7,
                            boxShadow: chatOpen
                                ? '0 0 16px rgba(124, 58, 237, 0.5), inset 0 1px 1px rgba(255,255,255,0.1)'
                                : '0 2px 8px rgba(124, 58, 237, 0.3)',
                        }}
                    >
                        <GeminiIcon size={14} />
                        AI Assistant
                    </button>
                    <button
                        onClick={handleRefreshTraffic}
                        disabled={isRefreshing}
                        className="btn-primary"
                        style={{
                            padding: '8px 18px', fontSize: 13,
                            display: 'flex', alignItems: 'center', gap: 6,
                            opacity: isRefreshing ? 0.6 : 1,
                        }}
                    >
                        {isRefreshing ? (
                            <>
                                <div className="spinner spinner-sm" style={{ borderTopColor: '#fff', borderColor: 'rgba(255,255,255,0.3)' }} />
                                Syncing...
                            </>
                        ) : (
                            <>
                                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                                </svg>
                                Refresh Traffic
                            </>
                        )}
                    </button>
                    <button
                        onClick={() => {
                            const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
                            window.open(`${API_URL}/api/download-report`, '_blank');
                        }}
                        style={{
                            background: 'var(--success)', color: '#fff',
                            border: 'none', borderRadius: 8, padding: '8px 18px',
                            fontWeight: 600, cursor: 'pointer', fontSize: 13,
                            display: 'flex', alignItems: 'center', gap: 6,
                        }}
                    >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path strokeLinecap="round" strokeLinejoin="round"
                                d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        Report
                    </button>
                    <button
                        onClick={() => navigate('/')}
                        className="btn-outline"
                        style={{ padding: '8px 18px', fontSize: 13, display: 'flex', alignItems: 'center', gap: 6 }}
                    >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                        </svg>
                        New Upload
                    </button>
                </div>
            </div>

            {/* Main Content - Split View */}
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
                {/* Left Panel - Statistics */}
                <div style={{
                    width: '33%', overflow: 'hidden',
                    borderRight: '1px solid var(--border)'
                }}>
                    <StatsPanel results={results} />
                </div>

                {/* Center Panel - Map */}
                <div style={{ flex: 1 }}>
                    <MapView results={results} />
                </div>

                {/* Right Panel - Chat (slides in from right) */}
                <ChatWidget
                    results={results}
                    isOpen={chatOpen}
                    onClose={() => setChatOpen(false)}
                />
            </div>
        </div>
    );
};

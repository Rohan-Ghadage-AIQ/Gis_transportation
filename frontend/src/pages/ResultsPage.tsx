import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/api';
import { MapView } from '../components/MapView';
import { StatsPanel } from '../components/StatsPanel';
import type { RouteResults } from '../types/api';

export const ResultsPage: React.FC = () => {
    const navigate = useNavigate();
    const [results, setResults] = useState<RouteResults | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [isRefreshing, setIsRefreshing] = useState(false);
    const [error, setError] = useState<string>('');
    const [notification, setNotification] = useState<{ message: string; type: 'success' | 'warning' } | null>(null);

    useEffect(() => {
        const fetchResults = async () => {
            try {
                const data = await apiService.getResults();
                setResults(data);
                setError('');
            } catch (err: any) {
                setError(err.response?.data?.detail || 'Failed to load results');
                // If no results available, redirect back to upload page
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
                setNotification({
                    message: `Traffic update: ${data.rerouted_vehicles.length} vehicles rerouted for better efficiency.`,
                    type: 'warning'
                });
            } else {
                setNotification({
                    message: "Traffic data updated. Current routes remain optimal.",
                    type: 'success'
                });
            }

            // Clear notification after 5 seconds
            setTimeout(() => setNotification(null), 5000);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Failed to refresh traffic');
        } finally {
            setIsRefreshing(false);
        }
    };

    if (isLoading) {
        return (
            <div className="min-h-screen bg-gray-900 flex items-center justify-center">
                <div className="text-center">
                    <div className="spinner mx-auto mb-4"></div>
                    <p className="text-white text-lg">Loading results...</p>
                </div>
            </div>
        );
    }

    if (error || !results) {
        return (
            <div className="min-h-screen bg-gray-900 flex items-center justify-center">
                <div className="text-center">
                    <svg
                        className="w-16 h-16 text-red-500 mx-auto mb-4"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path
                            strokeLinecap="round"
                            strokeLinejoin="round"
                            strokeWidth={2}
                            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                        />
                    </svg>
                    <p className="text-white text-lg mb-2">{error}</p>
                    <p className="text-gray-400">Redirecting to upload page...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="h-screen flex flex-col bg-gray-900 overflow-hidden relative">
            {/* Notification Toast */}
            {notification && (
                <div className={`fixed top-20 right-6 z-50 animate-bounce shadow-2xl rounded-lg px-6 py-4 flex items-center ${notification.type === 'warning' ? 'bg-amber-500 text-white' : 'bg-green-500 text-white'
                    }`}>
                    <svg className="w-6 h-6 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                    </svg>
                    <span className="font-semibold">{notification.message}</span>
                </div>
            )}

            {/* Header */}
            <div className="bg-gray-800 shadow-lg px-6 py-4 flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold text-white">
                        Optimized Vehicle Routes
                    </h1>
                    <p className="text-gray-400 text-sm">
                        {results.summary.total_fleets} vehicles · {results.summary.total_parcels} deliveries
                    </p>
                </div>
                <div className="flex gap-3">
                    <button
                        onClick={handleRefreshTraffic}
                        disabled={isRefreshing}
                        className={`${isRefreshing ? 'bg-gray-600' : 'bg-indigo-600 hover:bg-indigo-700'
                            } text-white px-6 py-2 rounded-lg transition-colors flex items-center`}
                    >
                        {isRefreshing ? (
                            <>
                                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></div>
                                Syncing...
                            </>
                        ) : (
                            <>
                                <svg className="w-5 h-5 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
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
                        className="bg-green-600 hover:bg-green-700 text-white px-6 py-2 rounded-lg transition-colors flex items-center"
                    >
                        <svg
                            className="w-5 h-5 mr-2"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                            />
                        </svg>
                        Download Report
                    </button>
                    <button
                        onClick={() => navigate('/')}
                        className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2 rounded-lg transition-colors flex items-center"
                    >
                        <svg
                            className="w-5 h-5 mr-2"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round"
                                strokeLinejoin="round"
                                strokeWidth={2}
                                d="M10 19l-7-7m0 0l7-7m-7 7h18"
                            />
                        </svg>
                        New Upload
                    </button>
                </div>
            </div>

            {/* Main Content - Split View */}
            <div className="flex-1 flex overflow-hidden">
                {/* Left Panel - Statistics */}
                <div className="w-1/3 overflow-hidden border-r border-gray-700">
                    <StatsPanel results={results} />
                </div>

                {/* Right Panel - Map */}
                <div className="flex-1">
                    <MapView results={results} />
                </div>
            </div>
        </div>
    );
};

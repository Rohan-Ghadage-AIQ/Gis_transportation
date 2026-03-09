import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { MapView } from '../components/MapView';
import { apiService } from '../services/api';

interface MaintStation {
    station_id: string;
    company_name?: string;
    lat: number;
    lon: number;
    arrival_time: string;
    status: string;
}

interface MaintVehicle {
    vehicle_id: number;
    technician_name: string;
    total_distance: number;
    total_tasks: number;
    total_service_mins: number;
    stations: MaintStation[];
    route_geometry: any[];
    color: string;
    clock_in: string;
    clock_out: string;
    work_duration: number;
}

interface MaintResults {
    vehicles: MaintVehicle[];
    summary: {
        total_distance: number;
        total_tasks: number;
        total_technicians: number;
        office: { lat: number; lon: number; name: string };
    };
    parcels: any[];
    unassigned_tasks: { station_id: string; lat: number; lon: number }[];
}

const BADGE = (status: string) => {
    if (status === 'ON TIME') return { bg: 'var(--success-light)', color: '#15803d' };
    if (status === 'EARLY') return { bg: 'var(--primary-light)', color: 'var(--primary-dark)' };
    return { bg: 'var(--danger-light)', color: '#b91c1c' };
};

export const MaintenanceResultsPage: React.FC = () => {
    const navigate = useNavigate();
    const [results, setResults] = useState<MaintResults | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState('');
    const [expandedVehicle, setExpandedVehicle] = useState<number | null>(null);

    useEffect(() => {
        (async () => {
            try {
                const data = await apiService.maintenanceResults();
                setResults(data);
            } catch (err: any) {
                setError(err.response?.data?.detail || 'Failed to load maintenance results');
                if (err.response?.status === 400) setTimeout(() => navigate('/maintenance'), 2000);
            } finally {
                setIsLoading(false);
            }
        })();
    }, [navigate]);

    if (isLoading) {
        return (
            <div style={{ minHeight: '100vh', background: 'var(--bg)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <div style={{ textAlign: 'center' }}>
                    <div className="spinner" style={{ margin: '0 auto 16px', borderTopColor: '#f97316' }} />
                    <p style={{ color: 'var(--text-muted)', fontSize: 16 }}>Loading maintenance results...</p>
                </div>
            </div>
        );
    }

    if (error || !results) {
        return (
            <div style={{ minHeight: '100vh', background: 'var(--bg)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <div style={{ textAlign: 'center' }}>
                    <div style={{ width: 56, height: 56, borderRadius: '50%', margin: '0 auto 16px', background: 'var(--danger-light)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28 }}>⚠</div>
                    <p style={{ color: 'var(--text)', fontSize: 16, marginBottom: 4 }}>{error}</p>
                    <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>Redirecting to upload page...</p>
                </div>
            </div>
        );
    }

    // Transform results into a shape compatible with the existing MapView component
    const mapResults = {
        vehicles: results.vehicles.map(v => ({
            vehicle_id: v.vehicle_id,
            stations: v.stations.map(s => ({ station_id: s.station_id, lat: s.lat, lon: s.lon, arrival_time: s.arrival_time, status: s.status })),
            route_geometry: v.route_geometry,
            total_distance: v.total_distance,
            cost: 0,
            total_weight: v.total_tasks,
            capacity: 100,
            utilization: 0,
            work_duration: v.work_duration,
            color: v.color,
            clock_in: v.clock_in,
            clock_out: v.clock_out,
        })),
        summary: {
            total_distance: results.summary.total_distance,
            total_cost: 0,
            total_parcels: results.summary.total_tasks,
            total_fleets: results.summary.total_technicians,
            warehouse: results.summary.office,
        },
        parcels: results.parcels,
        undelivered_parcels: results.unassigned_tasks,
    };

    return (
        <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: 'var(--bg)', overflow: 'hidden' }}>
            {/* Header */}
            <div style={{ padding: '12px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid var(--border)', background: 'var(--bg)' }}>
                <div>
                    <h1 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: 'var(--text)' }}>
                        🔧 Maintenance Route Plan
                    </h1>
                    <p style={{ margin: '2px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
                        {results.summary.total_technicians} technicians · {results.summary.total_tasks} tasks · {results.summary.total_distance.toFixed(1)} km
                    </p>
                </div>
                <div style={{ display: 'flex', gap: 10 }}>
                    <button onClick={() => navigate('/maintenance')}
                        style={{
                            background: 'transparent', color: '#f97316', border: '1.5px solid #f97316',
                            borderRadius: 8, padding: '8px 18px', fontWeight: 600, cursor: 'pointer', fontSize: 13,
                            display: 'flex', alignItems: 'center', gap: 6,
                        }}>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
                        </svg>
                        New Plan
                    </button>
                </div>
            </div>

            {/* Split View */}
            <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
                {/* Left Panel — Technician Stats */}
                <div style={{ width: '33%', overflow: 'auto', borderRight: '1px solid var(--border)', padding: 16 }}>
                    {/* Summary Cards */}
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginBottom: 16 }}>
                        {[
                            { label: 'Total Tasks', value: results.summary.total_tasks, icon: '📋' },
                            { label: 'Total Distance', value: `${results.summary.total_distance.toFixed(1)} km`, icon: '🛣️' },
                            { label: 'Technicians', value: results.summary.total_technicians, icon: '👷' },
                            { label: 'Unassigned', value: results.unassigned_tasks.length, icon: '⚠️' },
                        ].map((card, i) => (
                            <div key={i} style={{
                                background: 'var(--surface)', border: '1px solid var(--border-light)',
                                borderRadius: 10, padding: '12px 14px',
                            }}>
                                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, marginBottom: 2 }}>
                                    {card.icon} {card.label}
                                </div>
                                <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--text)' }}>{card.value}</div>
                            </div>
                        ))}
                    </div>

                    {/* Per-technician cards */}
                    {results.vehicles.map(v => (
                        <div key={v.vehicle_id} style={{
                            background: 'var(--surface)', border: '1px solid var(--border-light)',
                            borderRadius: 12, marginBottom: 10, overflow: 'hidden',
                        }}>
                            {/* Header */}
                            <div
                                onClick={() => setExpandedVehicle(expandedVehicle === v.vehicle_id ? null : v.vehicle_id)}
                                style={{
                                    padding: '12px 16px', cursor: 'pointer',
                                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                }}
                            >
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                    <div style={{
                                        width: 12, height: 12, borderRadius: '50%', background: v.color, flexShrink: 0,
                                    }} />
                                    <div>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{v.technician_name}</div>
                                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                            {v.clock_in}–{v.clock_out} · {v.total_tasks} tasks · {v.total_distance.toFixed(1)} km
                                        </div>
                                    </div>
                                </div>
                                <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{expandedVehicle === v.vehicle_id ? '▲' : '▼'}</span>
                            </div>

                            {/* Expanded stops */}
                            {expandedVehicle === v.vehicle_id && (
                                <div style={{ padding: '0 16px 12px' }}>
                                    {v.stations.map((s, i) => {
                                        const b = BADGE(s.status);
                                        return (
                                            <div key={i} style={{
                                                display: 'flex', alignItems: 'center', gap: 10,
                                                padding: '6px 0', borderTop: i > 0 ? '1px solid var(--border-light)' : 'none',
                                            }}>
                                                <div style={{
                                                    width: 22, height: 22, borderRadius: '50%',
                                                    background: v.color, color: '#fff', fontSize: 11, fontWeight: 700,
                                                    display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                                                }}>{i + 1}</div>
                                                <div style={{ flex: 1 }}>
                                                    <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>
                                                        {s.company_name || `Task ${s.station_id}`}
                                                    </div>
                                                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                                        ETA: {s.arrival_time}
                                                    </div>
                                                </div>
                                                <span className="badge" style={{ background: b.bg, color: b.color, fontSize: 10 }}>{s.status}</span>
                                            </div>
                                        );
                                    })}
                                </div>
                            )}
                        </div>
                    ))}

                    {/* Unassigned */}
                    {results.unassigned_tasks.length > 0 && (
                        <div style={{ marginTop: 16, padding: '12px 16px', background: 'var(--danger-light)', borderRadius: 10 }}>
                            <div style={{ fontSize: 13, fontWeight: 700, color: '#b91c1c', marginBottom: 6 }}>
                                ⚠️ {results.unassigned_tasks.length} Unassigned Tasks
                            </div>
                            {results.unassigned_tasks.map((u, i) => (
                                <div key={i} style={{ fontSize: 12, color: '#b91c1c' }}>
                                    Task {u.station_id}
                                </div>
                            ))}
                        </div>
                    )}
                </div>

                {/* Right Panel — Map */}
                <div style={{ flex: 1 }}>
                    <MapView results={mapResults as any} />
                </div>
            </div>
        </div>
    );
};

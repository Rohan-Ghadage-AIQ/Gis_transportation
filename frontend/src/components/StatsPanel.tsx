import React from 'react';
import type { RouteResults } from '../types/api';

interface StatsPanelProps {
    results: RouteResults;
}

/* ── SVG Icon Components ── */
const DistanceIcon = () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
    </svg>
);
const CostIcon = () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
);
const ParcelIcon = () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#d97706" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
    </svg>
);
const FleetIcon = () => (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#7c3aed" strokeWidth="2">
        <path strokeLinecap="round" strokeLinejoin="round" d="M8 17h.01M16 17h.01M3 11l1-9h16l1 9M3 11h18M3 11l2 7h14l2-7M7 17a1 1 0 11-2 0 1 1 0 012 0zm10 0a1 1 0 11-2 0 1 1 0 012 0z" />
    </svg>
);

export const StatsPanel: React.FC<StatsPanelProps> = ({ results }) => {
    const { summary, vehicles } = results;

    return (
        <div style={{
            height: '100%', overflowY: 'auto',
            background: 'var(--surface)', padding: 20
        }}>
            {/* Title */}
            <h2 style={{
                fontSize: 20, fontWeight: 800, color: 'var(--text)',
                margin: '0 0 16px', letterSpacing: '-0.01em'
            }}>
                Route Statistics
            </h2>

            {/* Weather Alert Banner */}
            {results.weather_alerts && results.weather_alerts.length > 0 && (
                <div style={{
                    background: results.weather_rerouted ? '#FEF2F2' : '#EFF6FF',
                    border: `1px solid ${results.weather_rerouted ? '#FECACA' : '#BFDBFE'}`,
                    borderRadius: 10, padding: '10px 14px', marginBottom: 14,
                    display: 'flex', alignItems: 'center', gap: 10,
                }}>
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
                        <path d="M20 15.5a3.5 3.5 0 00-3.5-3.5h-.52A5.002 5.002 0 007 11.5 3.5 3.5 0 004 15.5 3.5 3.5 0 007.5 19h9a3.5 3.5 0 003.5-3.5z"
                            fill={results.weather_rerouted ? '#DC2626' : '#3B82F6'} opacity="0.85" />
                        <path d="M8 21l1-3m3 3l1-3m3 3l1-3"
                            stroke={results.weather_rerouted ? '#DC2626' : '#3B82F6'} strokeWidth="2" strokeLinecap="round" />
                    </svg>
                    <div>
                        <div style={{ fontSize: 13, fontWeight: 700, color: results.weather_rerouted ? '#991B1B' : '#1E40AF' }}>
                            {results.weather_rerouted
                                ? '⛈️ Routes adjusted due to weather'
                                : '🌧️ Rain detected at delivery stations'}
                        </div>
                        <div style={{ fontSize: 11, color: results.weather_rerouted ? '#B91C1C' : '#3B82F6', marginTop: 2 }}>
                            {results.weather_alerts.length} station{results.weather_alerts.length > 1 ? 's' : ''} affected
                            {results.weather_alerts.filter(a => a.severity === 'heavy').length > 0 &&
                                ` • ${results.weather_alerts.filter(a => a.severity === 'heavy').length} waterlogging zones avoided`}
                        </div>
                    </div>
                </div>
            )}

            {/* Summary Cards */}
            <div style={{
                display: 'grid', gridTemplateColumns: '1fr 1fr',
                gap: 10, marginBottom: 20
            }}>
                <StatCard icon={<DistanceIcon />} label="Total Distance" value={`${summary.total_distance.toFixed(1)} km`} color="var(--primary)" />
                <StatCard icon={<CostIcon />} label="Total Cost" value={`₹${summary.total_cost.toFixed(0)}`} color="var(--success)" />
                <StatCard icon={<ParcelIcon />} label="Parcels" value={`${summary.total_parcels}`} color="var(--warning)" />
                <StatCard icon={<FleetIcon />} label="Active Fleets" value={`${summary.total_fleets}`} color="#8b5cf6" />
            </div>

            {/* Vehicle Breakdown */}
            <div style={{ marginBottom: 16 }}>
                <h3 style={{
                    fontSize: 15, fontWeight: 700, color: 'var(--text)',
                    margin: '0 0 10px'
                }}>
                    Vehicle Breakdown
                </h3>

                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {vehicles.map((vehicle) => (
                        <details
                            key={vehicle.vehicle_id}
                            style={{
                                background: 'var(--bg)',
                                border: '1px solid var(--border-light)',
                                borderRadius: 10,
                                overflow: 'hidden',
                            }}
                        >
                            <summary style={{
                                cursor: 'pointer', padding: '10px 14px',
                                display: 'flex', alignItems: 'center',
                                justifyContent: 'space-between', userSelect: 'none',
                                listStyle: 'none',
                            }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                    <div style={{
                                        width: 22, height: 22, borderRadius: '50%',
                                        background: vehicle.color,
                                        flexShrink: 0
                                    }} />
                                    <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text)' }}>
                                        Vehicle {vehicle.vehicle_id}
                                    </span>
                                    {results.rerouted_vehicles?.includes(vehicle.vehicle_id) && (
                                        <span className="badge badge-warning" style={{ fontSize: 10 }}>
                                            Rerouted
                                        </span>
                                    )}
                                </div>
                                <div style={{ display: 'flex', gap: 12, fontSize: 12, color: 'var(--text-muted)' }}>
                                    <span>{vehicle.stations.length} stops</span>
                                    <span>{vehicle.total_distance.toFixed(1)} km</span>
                                    <span style={{ fontSize: 16, color: 'var(--text-light)', transition: 'transform 0.2s' }}>▾</span>
                                </div>
                            </summary>

                            <div style={{
                                padding: '12px 14px',
                                borderTop: '1px solid var(--border-light)',
                                background: 'var(--surface)',
                            }}>
                                {/* Vehicle Stats Grid */}
                                <div style={{
                                    display: 'grid', gridTemplateColumns: '1fr 1fr',
                                    gap: 8, marginBottom: 12
                                }}>
                                    <MiniStat label="Distance" value={`${vehicle.total_distance.toFixed(2)} km`} />
                                    <MiniStat label="Cost" value={`₹${vehicle.cost.toFixed(0)}`} />
                                    <MiniStat label="Weight" value={`${vehicle.total_weight} kg`} />
                                    <MiniStat label="Capacity" value={`${vehicle.capacity} kg`} />
                                    <MiniStat label="Utilization" value={`${vehicle.utilization.toFixed(0)}%`}
                                        valueColor={vehicle.utilization > 90 ? 'var(--danger)' : vehicle.utilization > 70 ? 'var(--warning)' : 'var(--success)'} />
                                    <MiniStat label="Work Duration" value={`${(vehicle.work_duration / 60).toFixed(1)} hrs`} />
                                    <MiniStat label="Clock In" value={vehicle.clock_in} />
                                    <MiniStat label="Clock Out" value={vehicle.clock_out} />
                                </div>

                                {/* Delivery Timeline */}
                                {vehicle.stations.length > 0 && (
                                    <div>
                                        <div style={{
                                            fontSize: 11, fontWeight: 700, color: 'var(--text-muted)',
                                            textTransform: 'uppercase', letterSpacing: '0.05em',
                                            marginBottom: 6
                                        }}>
                                            Delivery Stops
                                        </div>
                                        <div style={{
                                            maxHeight: 200, overflowY: 'auto',
                                            borderRadius: 8, border: '1px solid var(--border-light)',
                                            background: 'var(--bg)'
                                        }}>
                                            {vehicle.stations.map((station, idx) => (
                                                <div key={idx} style={{
                                                    padding: '6px 10px', fontSize: 12,
                                                    borderBottom: idx < vehicle.stations.length - 1 ? '1px solid var(--border-light)' : 'none',
                                                    display: 'flex', justifyContent: 'space-between', alignItems: 'center'
                                                }}>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                        <span style={{
                                                            width: 20, height: 20, borderRadius: '50%',
                                                            background: 'var(--primary-light)', color: 'var(--primary-dark)',
                                                            display: 'flex', alignItems: 'center', justifyContent: 'center',
                                                            fontSize: 10, fontWeight: 700, flexShrink: 0
                                                        }}>
                                                            {idx + 1}
                                                        </span>
                                                        <span style={{ color: 'var(--text)', fontWeight: 500 }}>
                                                            {station.station_id}
                                                        </span>
                                                    </div>
                                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                                        <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                                                            {station.arrival_time}
                                                        </span>
                                                        <span className={`badge ${station.status === 'ON TIME' ? 'badge-success'
                                                            : station.status === 'IN_BUFFER' ? 'badge-primary'
                                                                : 'badge-danger'
                                                            }`} style={{ fontSize: 10 }}>
                                                            {station.status}
                                                        </span>
                                                    </div>
                                                </div>
                                            ))}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </details>
                    ))}
                </div>
            </div>

            {/* Undelivered Parcels */}
            {results.undelivered_parcels.length > 0 && (
                <div style={{
                    background: 'var(--danger-light)', border: '1px solid var(--danger)',
                    borderRadius: 10, padding: 14
                }}>
                    <h3 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 700, color: '#b91c1c' }}>
                        Undelivered Parcels ({results.undelivered_parcels.length})
                    </h3>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                        {results.undelivered_parcels.map((p, i) => (
                            <span key={i} className="badge badge-danger">
                                {p.station_id}
                            </span>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
};

// ── Sub-Components ──

const StatCard: React.FC<{ icon: React.ReactNode; label: string; value: string; color: string }> = ({ icon, label, value, color }) => (
    <div style={{
        background: 'var(--bg)', border: '1px solid var(--border-light)',
        borderRadius: 10, padding: '12px 14px',
        display: 'flex', alignItems: 'center', gap: 10
    }}>
        <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: `${color}18`, display: 'flex',
            alignItems: 'center', justifyContent: 'center',
            flexShrink: 0
        }}>
            {icon}
        </div>
        <div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>
                {label}
            </div>
            <div style={{ fontSize: 17, fontWeight: 800, color: 'var(--text)' }}>
                {value}
            </div>
        </div>
    </div>
);

const MiniStat: React.FC<{ label: string; value: string; valueColor?: string }> = ({ label, value, valueColor }) => (
    <div style={{
        background: 'var(--bg)', borderRadius: 6, padding: '6px 10px',
        border: '1px solid var(--border-light)'
    }}>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, textTransform: 'uppercase' }}>
            {label}
        </div>
        <div style={{ fontSize: 14, fontWeight: 700, color: valueColor || 'var(--text)' }}>
            {value}
        </div>
    </div>
);

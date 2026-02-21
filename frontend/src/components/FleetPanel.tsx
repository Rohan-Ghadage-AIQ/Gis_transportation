import React, { useState, useEffect } from 'react';
import { apiService } from '../services/api';
import type { VehicleConfig } from '../types/api';

interface FleetPanelProps {
    isOpen: boolean;
    onClose: () => void;
}

/** Convert minutes-from-midnight to HH:MM string */
const minToTime = (m: number): string => {
    const h = Math.floor(m / 60);
    const mm = m % 60;
    return `${String(h).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
};

/** Convert HH:MM string to minutes-from-midnight */
const timeToMin = (t: string): number => {
    const [h, m] = t.split(':').map(Number);
    return h * 60 + (m || 0);
};

export const FleetPanel: React.FC<FleetPanelProps> = ({ isOpen, onClose }) => {
    const [vehicles, setVehicles] = useState<VehicleConfig[]>([]);
    const [isLoading, setIsLoading] = useState(true);
    const [isSaving, setIsSaving] = useState(false);
    const [editingId, setEditingId] = useState<number | null>(null);
    const [editRow, setEditRow] = useState<VehicleConfig | null>(null);
    const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

    useEffect(() => {
        if (isOpen) {
            loadFleet();
        }
    }, [isOpen]);

    const loadFleet = async () => {
        setIsLoading(true);
        try {
            const data = await apiService.getFleet();
            setVehicles(data);
        } catch (err) {
            setMessage({ text: 'Failed to load fleet', type: 'error' });
        } finally {
            setIsLoading(false);
        }
    };

    const startEdit = (v: VehicleConfig) => {
        setEditingId(v.id ?? null);
        setEditRow({ ...v });
    };

    const cancelEdit = () => {
        // If editing a new unsaved vehicle (no id), remove it from the list
        if (editingId === -1) {
            setVehicles(prev => prev.filter(v => v.id != null));
        }
        setEditingId(null);
        setEditRow(null);
    };

    const saveVehicle = async (v: VehicleConfig) => {
        setIsSaving(true);
        try {
            const saved = await apiService.updateVehicle(v);
            setVehicles(prev => prev.map(x => (x.id === saved.id ? saved : x)));
            if (!v.id) {
                // Was a new vehicle — reload to get correct list
                await loadFleet();
            }
            setEditingId(null);
            setEditRow(null);
            setMessage({ text: 'Vehicle saved', type: 'success' });
            setTimeout(() => setMessage(null), 2000);
        } catch (err) {
            setMessage({ text: 'Failed to save', type: 'error' });
        } finally {
            setIsSaving(false);
        }
    };

    const deleteVehicle = async (id: number) => {
        if (!confirm('Delete this vehicle?')) return;
        try {
            await apiService.deleteVehicle(id);
            setVehicles(prev => prev.filter(v => v.id !== id));
            setMessage({ text: 'Vehicle deleted', type: 'success' });
            setTimeout(() => setMessage(null), 2000);
        } catch (err) {
            setMessage({ text: 'Failed to delete', type: 'error' });
        }
    };

    const addNewRow = async () => {
        const newVehicle: VehicleConfig = {
            name: `Vehicle ${vehicles.length + 1}`,
            capacity_kg: 150,
            cost_per_km: 15,
            shift_start: 540,
            shift_end: 1080,
        };
        // Save immediately to DB so it gets an id (edit/delete work right away)
        try {
            const saved = await apiService.updateVehicle(newVehicle);
            setVehicles(prev => [...prev, saved]);
            // Start editing the newly created vehicle
            setEditingId(saved.id ?? null);
            setEditRow({ ...saved });
            setMessage({ text: 'Vehicle added — edit details below', type: 'success' });
            setTimeout(() => setMessage(null), 2000);
        } catch (err) {
            setMessage({ text: 'Failed to add vehicle', type: 'error' });
        }
    };

    const saveAll = async () => {
        setIsSaving(true);
        try {
            for (const v of vehicles) {
                await apiService.updateVehicle(v);
            }
            await loadFleet();
            setMessage({ text: 'Fleet updated successfully!', type: 'success' });
            setTimeout(() => setMessage(null), 3000);
        } catch (err) {
            setMessage({ text: 'Failed to save fleet', type: 'error' });
        } finally {
            setIsSaving(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.3)', backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center'
        }}>
            <div style={{
                background: 'var(--bg)', borderRadius: 16,
                width: '92vw', maxWidth: 1100, maxHeight: '90vh',
                display: 'flex', flexDirection: 'column',
                boxShadow: '0 25px 50px rgba(0,0,0,0.15)',
                overflow: 'hidden'
            }}>
                {/* Header */}
                <div style={{
                    padding: '20px 28px', display: 'flex',
                    alignItems: 'center', justifyContent: 'space-between',
                    borderBottom: '1px solid var(--border)',
                    background: 'var(--surface)'
                }}>
                    <div>
                        <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: 'var(--text)', display: 'flex', alignItems: 'center', gap: 8 }}>
                            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2">
                                <path strokeLinecap="round" strokeLinejoin="round" d="M8 17h.01M16 17h.01M3 11l1-9h16l1 9M3 11h18M3 11l2 7h14l2-7M7 17a1 1 0 11-2 0 1 1 0 012 0zm10 0a1 1 0 11-2 0 1 1 0 012 0z" />
                            </svg>
                            Fleet Configuration
                        </h2>
                        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
                            {vehicles.length} vehicles · Edit capacity, cost/km, and shift timing
                        </p>
                    </div>
                    <button onClick={onClose} style={{
                        background: 'none', border: 'none', fontSize: 24,
                        cursor: 'pointer', color: 'var(--text-muted)',
                        width: 36, height: 36, borderRadius: 8,
                        display: 'flex', alignItems: 'center', justifyContent: 'center'
                    }}
                        onMouseOver={e => (e.currentTarget.style.background = 'var(--primary-light)')}
                        onMouseOut={e => (e.currentTarget.style.background = 'none')}
                    >✕</button>
                </div>

                {/* Notification */}
                {message && (
                    <div style={{
                        padding: '10px 28px',
                        background: message.type === 'success' ? 'var(--success-light)' : 'var(--danger-light)',
                        color: message.type === 'success' ? '#15803d' : '#b91c1c',
                        fontSize: 13, fontWeight: 600
                    }}>
                        {message.text}
                    </div>
                )}

                {/* Table */}
                <div style={{ flex: 1, overflowY: 'auto', padding: '16px 28px' }}>
                    {isLoading ? (
                        <div style={{ textAlign: 'center', padding: 60, color: 'var(--text-muted)' }}>
                            <div className="spinner" style={{ margin: '0 auto 12px' }}></div>
                            Loading fleet...
                        </div>
                    ) : (
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
                            <thead>
                                <tr style={{ background: 'var(--primary)', color: '#fff' }}>
                                    <th style={thStyle}>#</th>
                                    <th style={thStyle}>Name</th>
                                    <th style={thStyle}>Capacity (kg)</th>
                                    <th style={thStyle}>Cost/km (₹)</th>
                                    <th style={thStyle}>Shift Start</th>
                                    <th style={thStyle}>Shift End</th>
                                    <th style={{ ...thStyle, textAlign: 'center' }}>Actions</th>
                                </tr>
                            </thead>
                            <tbody>
                                {vehicles.map((v, idx) => {
                                    const isEditing = (v.id != null && editingId === v.id) || (!v.id && editingId === -1 && idx === vehicles.length - 1);
                                    const row = isEditing && editRow ? editRow : v;

                                    return (
                                        <tr key={v.id ?? `new-${idx}`}
                                            style={{
                                                borderBottom: '1px solid var(--border-light)',
                                                background: isEditing ? 'var(--primary-light)' : idx % 2 === 0 ? 'var(--bg)' : 'var(--surface)'
                                            }}
                                        >
                                            <td style={tdStyle}>{idx + 1}</td>
                                            <td style={tdStyle}>
                                                {isEditing ? (
                                                    <input value={row.name} onChange={e => setEditRow({ ...row, name: e.target.value })}
                                                        style={inputStyle} />
                                                ) : v.name}
                                            </td>
                                            <td style={tdStyle}>
                                                {isEditing ? (
                                                    <input type="number" value={row.capacity_kg}
                                                        onChange={e => setEditRow({ ...row, capacity_kg: parseInt(e.target.value) || 0 })}
                                                        style={{ ...inputStyle, width: 80 }} />
                                                ) : `${v.capacity_kg} kg`}
                                            </td>
                                            <td style={tdStyle}>
                                                {isEditing ? (
                                                    <input type="number" step="0.5" value={row.cost_per_km}
                                                        onChange={e => setEditRow({ ...row, cost_per_km: parseFloat(e.target.value) || 0 })}
                                                        style={{ ...inputStyle, width: 80 }} />
                                                ) : `₹${v.cost_per_km}`}
                                            </td>
                                            <td style={tdStyle}>
                                                {isEditing ? (
                                                    <input type="time" value={minToTime(row.shift_start)}
                                                        onChange={e => setEditRow({ ...row, shift_start: timeToMin(e.target.value) })}
                                                        style={inputStyle} />
                                                ) : minToTime(v.shift_start)}
                                            </td>
                                            <td style={tdStyle}>
                                                {isEditing ? (
                                                    <input type="time" value={minToTime(row.shift_end)}
                                                        onChange={e => setEditRow({ ...row, shift_end: timeToMin(e.target.value) })}
                                                        style={inputStyle} />
                                                ) : minToTime(v.shift_end)}
                                            </td>
                                            <td style={{ ...tdStyle, textAlign: 'center' }}>
                                                {isEditing ? (
                                                    <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
                                                        <button onClick={() => saveVehicle(row)} disabled={isSaving}
                                                            style={{ ...actionBtn, background: 'var(--success)', color: '#fff' }}>
                                                            ✓
                                                        </button>
                                                        <button onClick={cancelEdit}
                                                            style={{ ...actionBtn, background: 'var(--border)', color: 'var(--text)' }}>
                                                            ✕
                                                        </button>
                                                    </div>
                                                ) : (
                                                    <div style={{ display: 'flex', gap: 6, justifyContent: 'center' }}>
                                                        <button onClick={() => startEdit(v)}
                                                            style={{ ...actionBtn, background: 'var(--primary-light)', color: 'var(--primary-dark)' }}>
                                                            ✎
                                                        </button>
                                                        {v.id && (
                                                            <button onClick={() => deleteVehicle(v.id!)}
                                                                style={{ ...actionBtn, background: 'var(--danger-light)', color: '#b91c1c' }}>
                                                                🗑
                                                            </button>
                                                        )}
                                                    </div>
                                                )}
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    )}
                </div>

                {/* Footer */}
                <div style={{
                    padding: '16px 28px', display: 'flex', justifyContent: 'space-between',
                    alignItems: 'center', borderTop: '1px solid var(--border)',
                    background: 'var(--surface)'
                }}>
                    <button onClick={addNewRow} style={{
                        background: 'var(--primary-light)', color: 'var(--primary-dark)',
                        border: '1.5px solid var(--primary)', borderRadius: 8,
                        padding: '8px 20px', fontWeight: 600, cursor: 'pointer',
                        fontSize: 14
                    }}>
                        + Add Vehicle
                    </button>
                    <button onClick={saveAll} disabled={isSaving} style={{
                        background: 'var(--primary)', color: '#fff',
                        border: 'none', borderRadius: 8,
                        padding: '10px 32px', fontWeight: 600, cursor: 'pointer',
                        fontSize: 15, opacity: isSaving ? 0.6 : 1,
                    }}>
                        {isSaving ? 'Saving...' : 'Update Fleet'}
                    </button>
                </div>
            </div>
        </div>
    );
};

// ── Inline Styles ──

const thStyle: React.CSSProperties = {
    padding: '12px 14px', textAlign: 'left', fontWeight: 600,
    fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.05em',
};

const tdStyle: React.CSSProperties = {
    padding: '10px 14px', fontSize: 14, color: 'var(--text)',
};

const inputStyle: React.CSSProperties = {
    border: '1.5px solid var(--primary)', borderRadius: 6,
    padding: '5px 10px', fontSize: 14, outline: 'none',
    background: 'var(--bg)', color: 'var(--text)',
};

const actionBtn: React.CSSProperties = {
    width: 30, height: 30, borderRadius: 6, border: 'none',
    cursor: 'pointer', fontSize: 13, fontWeight: 600,
    display: 'flex', alignItems: 'center', justifyContent: 'center',
};

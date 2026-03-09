import React, { useState, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/api';

interface Technician {
    id: number;
    name: string;
    shift_start: number;
    shift_end: number;
    shift_label: string;
}

export const MaintenanceUploadPage: React.FC = () => {
    const navigate = useNavigate();
    const [file, setFile] = useState<File | null>(null);
    const [tasks, setTasks] = useState<any[]>([]);
    const [taskColumns, setTaskColumns] = useState<string[]>([]);
    const [technicians, setTechnicians] = useState<Technician[]>([]);
    const [teamSize, setTeamSize] = useState(3);
    const [officeLat, setOfficeLat] = useState('19.05507294355211');
    const [officeLon, setOfficeLon] = useState('72.87538873375874');
    const [isLoading, setIsLoading] = useState(false);
    const [loadingMsg, setLoadingMsg] = useState('');
    const [error, setError] = useState('');
    const [isDragActive, setIsDragActive] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragActive(false);
        const f = e.dataTransfer.files?.[0];
        if (f && (f.name.endsWith('.xlsx') || f.name.endsWith('.xls'))) {
            setFile(f);
            handleFileLoad(f);
        } else {
            setError('Please upload an .xlsx file with two sheets.');
        }
    }, []);

    const handleFileLoad = async (f: File) => {
        setError('');
        setIsLoading(true);
        setLoadingMsg('Uploading & geocoding task addresses...');
        try {
            const res = await apiService.maintenanceUpload(f);
            setTasks(res.tasks || []);
            setTaskColumns(res.task_columns || []);
            setTechnicians(res.technicians || []);
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Upload failed');
        } finally {
            setIsLoading(false);
        }
    };

    const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
        const selected = e.target.files?.[0];
        if (selected) {
            setFile(selected);
            handleFileLoad(selected);
        }
    };

    const handleCompute = async () => {
        setIsLoading(true);
        setLoadingMsg('Computing optimized maintenance routes…');
        setError('');
        try {
            await apiService.maintenanceCompute({
                team_size: teamSize,
                office_lat: parseFloat(officeLat),
                office_lon: parseFloat(officeLon),
            });
            navigate('/maintenance-results');
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Computation failed');
            setIsLoading(false);
        }
    };

    const fmtMin = (m: number) => `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;

    return (
        <div style={{ minHeight: '100vh', background: 'var(--bg)', position: 'relative', overflow: 'hidden' }}>
            {/* Animated Background */}
            <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }}>
                {[...Array(6)].map((_, i) => (
                    <div key={`dot-${i}`} className="floating-dot" style={{
                        left: `${10 + i * 15}%`,
                        animationDelay: `${i * 1.2}s`,
                        animationDuration: `${6 + i * 0.8}s`,
                        background: '#f97316',
                    }} />
                ))}
                <svg style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', opacity: 0.06 }}>
                    <path className="route-line" d="M 0 200 Q 200 100, 400 200 T 800 200 T 1200 200 T 1600 200" style={{ stroke: '#f97316' }} />
                    <path className="route-line" d="M 0 400 Q 300 300, 500 400 T 900 350 T 1300 400 T 1700 350" style={{ animationDelay: '2s', stroke: '#f97316' }} />
                </svg>
                <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, height: '40%', background: 'linear-gradient(transparent, var(--bg))' }} />
            </div>

            {/* Top Nav */}
            <nav style={{
                position: 'relative', zIndex: 10,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '16px 32px',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{
                        width: 38, height: 38, borderRadius: 10,
                        background: 'linear-gradient(135deg, #f97316, #ea580c)',
                        display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 20,
                    }}>🔧</div>
                    <div>
                        <div style={{ fontSize: 17, fontWeight: 800, color: 'var(--text)', letterSpacing: '-0.02em' }}>
                            AIQ Maintenance Team
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500, marginTop: -2 }}>
                            Field Service Planning Platform
                        </div>
                    </div>
                </div>
            </nav>

            {/* Main Content */}
            <div style={{
                position: 'relative', zIndex: 10,
                maxWidth: 900, margin: '0 auto', padding: '24px 24px 0',
            }}>
                {/* Title */}
                <div style={{ textAlign: 'center', marginBottom: 28 }}>
                    <div style={{ display: 'flex', justifyContent: 'center', gap: 20, marginBottom: 20 }}>
                        {[
                            { label: 'Technicians', icon: '👷' },
                            { label: 'Time Slots', icon: '🕐' },
                            { label: 'Route Plan', icon: '🗺️' },
                        ].map((item, i) => (
                            <div key={i} className="hero-icon-pill" style={{ animationDelay: `${i * 0.2}s` }}>
                                <span style={{ fontSize: 16 }}>{item.icon}</span>
                                <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{item.label}</span>
                            </div>
                        ))}
                    </div>
                    <h1 style={{ fontSize: 36, fontWeight: 900, color: 'var(--text)', margin: '0 0 10px', letterSpacing: '-0.03em' }}>
                        <span style={{ color: '#f97316' }}>Plan</span> your maintenance,{' '}
                        <span style={{ color: '#f97316' }}>optimize</span> routes
                    </h1>
                    <p style={{ fontSize: 15, color: 'var(--text-muted)', maxWidth: 560, margin: '0 auto' }}>
                        Upload your Excel with task locations & technician shifts. We'll assign and route everyone optimally.
                    </p>
                </div>

                {/* Config Row */}
                <div style={{
                    display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap',
                }}>
                    <div style={{ flex: 1, minWidth: 180, background: 'var(--surface)', border: '1px solid var(--border-light)', borderRadius: 12, padding: '12px 16px' }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Team Size</label>
                        <input type="number" min={1} max={20} value={teamSize} onChange={e => setTeamSize(Math.max(1, parseInt(e.target.value) || 1))}
                            style={{ display: 'block', width: '100%', marginTop: 4, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border)', fontSize: 15, fontWeight: 700, color: 'var(--text)', background: 'var(--bg)' }} />
                    </div>
                    <div style={{ flex: 1, minWidth: 180, background: 'var(--surface)', border: '1px solid var(--border-light)', borderRadius: 12, padding: '12px 16px' }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Office Latitude</label>
                        <input type="text" value={officeLat} onChange={e => setOfficeLat(e.target.value)}
                            style={{ display: 'block', width: '100%', marginTop: 4, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border)', fontSize: 13, color: 'var(--text)', background: 'var(--bg)' }} />
                    </div>
                    <div style={{ flex: 1, minWidth: 180, background: 'var(--surface)', border: '1px solid var(--border-light)', borderRadius: 12, padding: '12px 16px' }}>
                        <label style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Office Longitude</label>
                        <input type="text" value={officeLon} onChange={e => setOfficeLon(e.target.value)}
                            style={{ display: 'block', width: '100%', marginTop: 4, padding: '6px 10px', borderRadius: 8, border: '1px solid var(--border)', fontSize: 13, color: 'var(--text)', background: 'var(--bg)' }} />
                    </div>
                </div>

                {/* Upload Card */}
                <div
                    onDrop={handleDrop}
                    onDragOver={e => { e.preventDefault(); setIsDragActive(true); }}
                    onDragLeave={() => setIsDragActive(false)}
                    onClick={() => !file && fileInputRef.current?.click()}
                    style={{
                        background: 'var(--surface)',
                        border: `2px dashed ${isDragActive ? '#f97316' : 'var(--border)'}`,
                        borderRadius: 16, padding: file ? '20px' : '40px 32px',
                        cursor: file ? 'default' : 'pointer',
                        transition: 'all 0.2s',
                        boxShadow: isDragActive ? '0 0 0 4px rgba(249,115,22,0.15)' : 'var(--shadow)',
                        marginBottom: 20,
                    }}
                >
                    <input ref={fileInputRef} type="file" accept=".xlsx,.xls" onChange={handleFileChange} style={{ display: 'none' }} />

                    {!file ? (
                        <div style={{ textAlign: 'center' }}>
                            <div style={{
                                width: 56, height: 56, borderRadius: 14,
                                background: 'rgba(249,115,22,0.1)', margin: '0 auto 14px',
                                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 28,
                            }}>📋</div>
                            <p style={{ fontSize: 15, fontWeight: 700, color: 'var(--text)', margin: '0 0 4px' }}>
                                Drop your maintenance Excel here
                            </p>
                            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
                                or <span style={{ color: '#f97316', fontWeight: 600 }}>click to browse</span> — requires 2 sheets (.xlsx)
                            </p>
                        </div>
                    ) : (
                        <div>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: tasks.length ? 14 : 0 }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                    <div style={{
                                        width: 40, height: 40, borderRadius: 10,
                                        background: 'var(--success-light)',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    }}>
                                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#16a34a" strokeWidth="2">
                                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                                        </svg>
                                    </div>
                                    <div style={{ textAlign: 'left' }}>
                                        <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{file.name}</div>
                                        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                                            {(file.size / 1024).toFixed(1)} KB
                                            {tasks.length > 0 && ` · ${tasks.length} tasks`}
                                            {technicians.length > 0 && ` · ${technicians.length} technicians`}
                                        </div>
                                    </div>
                                </div>
                                <button onClick={(e) => { e.stopPropagation(); setFile(null); setTasks([]); setTechnicians([]); }}
                                    style={{ background: 'var(--border-light)', border: 'none', borderRadius: 8, width: 32, height: 32, cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>✕</button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Tasks Table */}
                {tasks.length > 0 && (
                    <div style={{ marginBottom: 20 }}>
                        <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
                            📍 Maintenance Tasks ({tasks.length})
                        </h3>
                        <div style={{ maxHeight: 280, overflowY: 'auto', borderRadius: 10, border: '1px solid var(--border-light)' }}>
                            <table className="data-table" style={{ width: '100%', fontSize: 12 }}>
                                <thead>
                                    <tr>
                                        {taskColumns.map(col => (
                                            <th key={col} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 11 }}>{col}</th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {tasks.map((row, i) => (
                                        <tr key={i}>
                                            {taskColumns.map((col, j) => (
                                                <td key={j} style={{ padding: '6px 10px' }}>{String(row[col] ?? '')}</td>
                                            ))}
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {/* Technicians Table */}
                {technicians.length > 0 && (
                    <div style={{ marginBottom: 20 }}>
                        <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)', marginBottom: 8 }}>
                            👷 Technicians ({technicians.length})
                            {teamSize < technicians.length && (
                                <span style={{ fontWeight: 500, fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>
                                    (using top {teamSize})
                                </span>
                            )}
                        </h3>
                        <div style={{ maxHeight: 200, overflowY: 'auto', borderRadius: 10, border: '1px solid var(--border-light)' }}>
                            <table className="data-table" style={{ width: '100%', fontSize: 12 }}>
                                <thead>
                                    <tr>
                                        <th style={{ padding: '8px 10px', fontSize: 11 }}>ID</th>
                                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Name</th>
                                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Shift Timing</th>
                                        <th style={{ padding: '8px 10px', fontSize: 11 }}>Start</th>
                                        <th style={{ padding: '8px 10px', fontSize: 11 }}>End</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {technicians.map((t, i) => (
                                        <tr key={i} style={{ opacity: i < teamSize ? 1 : 0.4 }}>
                                            <td style={{ padding: '6px 10px' }}>{t.id}</td>
                                            <td style={{ padding: '6px 10px', fontWeight: 600 }}>{t.name}</td>
                                            <td style={{ padding: '6px 10px' }}>{t.shift_label}</td>
                                            <td style={{ padding: '6px 10px' }}>{fmtMin(t.shift_start)}</td>
                                            <td style={{ padding: '6px 10px' }}>{fmtMin(t.shift_end)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {/* Error */}
                {error && (
                    <div style={{ background: 'var(--danger-light)', color: '#b91c1c', padding: '10px 16px', borderRadius: 10, fontSize: 13, fontWeight: 600, marginBottom: 16 }}>{error}</div>
                )}

                {/* Compute Button */}
                {file && tasks.length > 0 && technicians.length > 0 && (
                    <button
                        onClick={handleCompute}
                        disabled={isLoading}
                        style={{
                            width: '100%', padding: '14px 24px', fontSize: 16,
                            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
                            opacity: isLoading ? 0.7 : 1,
                            background: '#f97316', color: '#fff', border: 'none',
                            borderRadius: 10, fontWeight: 700, cursor: 'pointer',
                            transition: 'background 0.15s',
                        }}
                        onMouseOver={e => { if (!isLoading) e.currentTarget.style.background = '#ea580c'; }}
                        onMouseOut={e => e.currentTarget.style.background = '#f97316'}
                    >
                        {isLoading ? (
                            <>
                                <div className="spinner spinner-sm" style={{ borderTopColor: '#fff', borderColor: 'rgba(255,255,255,0.3)' }} />
                                {loadingMsg}
                            </>
                        ) : (
                            <>🚀 Optimize Maintenance Routes</>
                        )}
                    </button>
                )}

                {/* Feature strip */}
                <div style={{ display: 'flex', justifyContent: 'center', gap: 32, marginTop: 32, paddingTop: 20, borderTop: '1px solid var(--border-light)' }}>
                    {[
                        { icon: '🗺️', label: 'Google Maps Routing' },
                        { icon: '🚦', label: 'Live Traffic' },
                        { icon: '⏰', label: 'Shift-Aware Scheduling' },
                    ].map((feat, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span style={{ fontSize: 14 }}>{feat.icon}</span>
                            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)' }}>{feat.label}</span>
                        </div>
                    ))}
                </div>
            </div>

            {/* Loading Overlay */}
            {isLoading && (
                <div style={{
                    position: 'fixed', inset: 0, zIndex: 100,
                    background: 'rgba(255,255,255,0.85)', backdropFilter: 'blur(8px)',
                    display: 'flex', flexDirection: 'column',
                    alignItems: 'center', justifyContent: 'center',
                }}>
                    <div className="spinner" style={{ width: 48, height: 48, marginBottom: 16, borderTopColor: '#f97316' }} />
                    <p style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)' }}>{loadingMsg}</p>
                    <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>This may take a moment...</p>
                </div>
            )}
        </div>
    );
};

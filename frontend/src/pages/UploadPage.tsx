import React, { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiService } from '../services/api';
import { FleetPanel } from '../components/FleetPanel';

export const UploadPage: React.FC = () => {
    const navigate = useNavigate();
    const [file, setFile] = useState<File | null>(null);
    const [previewData, setPreviewData] = useState<any[] | null>(null);
    const [isLoading, setIsLoading] = useState(false);
    const [loadingMsg, setLoadingMsg] = useState('');
    const [error, setError] = useState('');
    const [showFleet, setShowFleet] = useState(false);
    const [isDragActive, setIsDragActive] = useState(false);
    const [isEdited, setIsEdited] = useState(false);
    const fileInputRef = useRef<HTMLInputElement>(null);

    const handleDrop = useCallback((e: React.DragEvent) => {
        e.preventDefault();
        setIsDragActive(false);
        const droppedFile = e.dataTransfer.files?.[0];
        if (droppedFile && (droppedFile.name.endsWith('.xlsx') || droppedFile.name.endsWith('.csv'))) {
            setFile(droppedFile);
            handleFileLoad(droppedFile);
        } else {
            setError('Please upload an .xlsx or .csv file');
        }
    }, []);

    const handleFileLoad = async (f: File) => {
        setError('');
        setIsLoading(true);
        setLoadingMsg('Uploading file...');
        try {
            const res = await apiService.uploadFile(f);
            setPreviewData(res.data);
            setIsEdited(false);
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
        try {
            // Auto-save edits before computing
            if (isEdited && previewData) {
                setLoadingMsg('Saving edits...');
                await apiService.updateData(previewData);
                setIsEdited(false);
            }
            setLoadingMsg('Computing optimal routes...');
            await apiService.computeRoutes();
            navigate('/results');
        } catch (err: any) {
            setError(err.response?.data?.detail || 'Computation failed');
            setIsLoading(false);
        }
    };

    return (
        <div style={{ minHeight: '100vh', background: 'var(--bg)', position: 'relative', overflow: 'hidden' }}>
            <FleetPanel isOpen={showFleet} onClose={() => setShowFleet(false)} />

            {/* ── Animated Background ── */}
            <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', pointerEvents: 'none' }}>
                {/* Floating route dots */}
                {[...Array(6)].map((_, i) => (
                    <div key={`dot-${i}`} className="floating-dot" style={{
                        left: `${10 + i * 15}%`,
                        animationDelay: `${i * 1.2}s`,
                        animationDuration: `${6 + i * 0.8}s`,
                    }} />
                ))}
                {/* Animated route lines */}
                <svg style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', opacity: 0.06 }}>
                    <path className="route-line" d="M 0 200 Q 200 100, 400 200 T 800 200 T 1200 200 T 1600 200" />
                    <path className="route-line" d="M 0 400 Q 300 300, 500 400 T 900 350 T 1300 400 T 1700 350" style={{ animationDelay: '2s' }} />
                    <path className="route-line" d="M 0 600 Q 250 500, 450 550 T 850 500 T 1250 550 T 1650 500" style={{ animationDelay: '4s' }} />
                </svg>
                {/* Gradient overlay */}
                <div style={{
                    position: 'absolute', bottom: 0, left: 0, right: 0, height: '40%',
                    background: 'linear-gradient(transparent, var(--bg))'
                }} />
            </div>

            {/* ── Top Nav ── */}
            <nav style={{
                position: 'relative', zIndex: 10,
                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                padding: '16px 32px',
            }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <div style={{
                        width: 38, height: 38, borderRadius: 10,
                        background: 'linear-gradient(135deg, var(--primary), var(--primary-dark))',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.5">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l5.447 2.724A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
                        </svg>
                    </div>
                    <div>
                        <div style={{ fontSize: 17, fontWeight: 800, color: 'var(--text)', letterSpacing: '-0.02em' }}>
                            AIQ Logistics
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 500, marginTop: -2 }}>
                            Route Optimization Platform
                        </div>
                    </div>
                </div>
                <button
                    onClick={() => setShowFleet(true)}
                    style={{
                        display: 'flex', alignItems: 'center', gap: 8,
                        background: 'var(--surface)', border: '1.5px solid var(--border)',
                        borderRadius: 10, padding: '9px 18px', cursor: 'pointer',
                        fontWeight: 600, fontSize: 13, color: 'var(--text)',
                        transition: 'all 0.2s',
                    }}
                    onMouseOver={e => { e.currentTarget.style.borderColor = 'var(--primary)'; e.currentTarget.style.boxShadow = '0 2px 8px rgba(92,157,237,0.15)'; }}
                    onMouseOut={e => { e.currentTarget.style.borderColor = 'var(--border)'; e.currentTarget.style.boxShadow = 'none'; }}
                >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path strokeLinecap="round" strokeLinejoin="round" d="M8 17h.01M16 17h.01M3 11l1-9h16l1 9M3 11h18M3 11l2 7h14l2-7M7 17a1 1 0 11-2 0 1 1 0 012 0zm10 0a1 1 0 11-2 0 1 1 0 012 0z" />
                    </svg>
                    Fleet Config
                </button>
            </nav>

            {/* ── Hero Section ── */}
            <div style={{
                position: 'relative', zIndex: 10,
                maxWidth: 720, margin: '0 auto', padding: '48px 24px 0',
                textAlign: 'center',
            }}>
                {/* Animated feature icons */}
                <div style={{
                    display: 'flex', justifyContent: 'center', gap: 20, marginBottom: 28
                }}>
                    {[
                        { d: "M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l5.447 2.724A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7", label: "Routes" },
                        { d: "M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4", label: "Parcels" },
                        { d: "M13 10V3L4 14h7v7l9-11h-7z", label: "Live Traffic" },
                    ].map((item, i) => (
                        <div key={i} className="hero-icon-pill" style={{ animationDelay: `${i * 0.2}s` }}>
                            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2">
                                <path strokeLinecap="round" strokeLinejoin="round" d={item.d} />
                            </svg>
                            <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text)' }}>{item.label}</span>
                        </div>
                    ))}
                </div>

                <h1 style={{
                    fontSize: 42, fontWeight: 900, color: 'var(--text)',
                    margin: '0 0 12px', lineHeight: 1.15, letterSpacing: '-0.03em',
                }}>
                    <span style={{ color: 'var(--primary)' }}>Optimize</span>{' '}
                    routes,{' '}
                    <span style={{ color: 'var(--primary)' }}>deliver</span>{' '}
                    faster
                </h1>

                <p style={{
                    fontSize: 17, color: 'var(--text-muted)', lineHeight: 1.6,
                    margin: '0 auto 36px', maxWidth: 520,
                }}>
                    Upload your delivery file and we'll compute the most efficient
                    routes for your entire fleet — powered by AI optimization.
                </p>

                {/* ── Upload Card ── */}
                <div
                    onDrop={handleDrop}
                    onDragOver={e => { e.preventDefault(); setIsDragActive(true); }}
                    onDragLeave={() => setIsDragActive(false)}
                    onClick={() => !file && fileInputRef.current?.click()}
                    style={{
                        background: 'var(--surface)',
                        border: `2px dashed ${isDragActive ? 'var(--primary)' : 'var(--border)'}`,
                        borderRadius: 16, padding: file ? '24px' : '48px 32px',
                        cursor: file ? 'default' : 'pointer',
                        transition: 'all 0.2s',
                        boxShadow: isDragActive ? '0 0 0 4px var(--primary-light)' : 'var(--shadow)',
                        marginBottom: 24,
                    }}
                >
                    <input
                        ref={fileInputRef}
                        type="file"
                        accept=".xlsx,.csv"
                        onChange={handleFileChange}
                        style={{ display: 'none' }}
                    />

                    {!file ? (
                        <div>
                            <div style={{
                                width: 56, height: 56, borderRadius: 14,
                                background: 'var(--primary-light)', margin: '0 auto 16px',
                                display: 'flex', alignItems: 'center', justifyContent: 'center',
                            }}>
                                <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
                                </svg>
                            </div>
                            <p style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)', margin: '0 0 6px' }}>
                                Drop your delivery file here
                            </p>
                            <p style={{ fontSize: 13, color: 'var(--text-muted)', margin: 0 }}>
                                or <span style={{ color: 'var(--primary)', fontWeight: 600 }}>click to browse</span> — supports .xlsx, .csv
                            </p>
                        </div>
                    ) : (
                        <div>
                            {/* File info */}
                            <div style={{
                                display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                marginBottom: previewData ? 16 : 0,
                            }}>
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
                                            {previewData && ` · ${previewData.length} deliveries`}
                                        </div>
                                    </div>
                                </div>
                                <button
                                    onClick={(e) => { e.stopPropagation(); setFile(null); setPreviewData(null); }}
                                    style={{
                                        background: 'var(--border-light)', border: 'none', borderRadius: 8,
                                        width: 32, height: 32, cursor: 'pointer', fontSize: 16, color: 'var(--text-muted)',
                                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                                    }}
                                >✕</button>
                            </div>

                            {/* Data preview table — EDITABLE */}
                            {previewData && previewData.length > 0 && (
                                <>
                                    <div style={{
                                        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                                        marginBottom: 8,
                                    }}>
                                        <span style={{ fontSize: 12, color: 'var(--text-muted)', fontWeight: 600 }}>
                                            ✏️ Click any cell to edit
                                        </span>
                                        {isEdited && (
                                            <button
                                                onClick={async (e) => {
                                                    e.stopPropagation();
                                                    try {
                                                        setIsLoading(true);
                                                        setLoadingMsg('Saving changes...');
                                                        await apiService.updateData(previewData);
                                                        setIsEdited(false);
                                                    } catch (err: any) {
                                                        setError(err.response?.data?.detail || 'Failed to save');
                                                    } finally {
                                                        setIsLoading(false);
                                                    }
                                                }}
                                                style={{
                                                    background: 'var(--primary)', color: '#fff', border: 'none',
                                                    borderRadius: 8, padding: '5px 14px', fontSize: 12,
                                                    fontWeight: 700, cursor: 'pointer',
                                                }}
                                            >
                                                💾 Save Changes
                                            </button>
                                        )}
                                    </div>
                                    <div style={{
                                        maxHeight: 400, overflowY: 'auto',
                                        borderRadius: 10, border: '1px solid var(--border-light)',
                                    }}>
                                        <table className="data-table" style={{ width: '100%', fontSize: 12 }}>
                                            <thead>
                                                <tr>
                                                    {Object.keys(previewData[0]).map(col => (
                                                        <th key={col} style={{ padding: '8px 10px', textAlign: 'left', fontSize: 11 }}>{col}</th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {previewData.map((row, i) => (
                                                    <tr key={i}>
                                                        {Object.entries(row).map(([key, val]: [string, any], j) => (
                                                            <td key={j} style={{ padding: '2px 4px' }}>
                                                                <input
                                                                    type="text"
                                                                    defaultValue={typeof val === 'number' ? val : String(val ?? '')}
                                                                    onBlur={(e) => {
                                                                        const newVal = e.target.value;
                                                                        const parsed = Number(newVal);
                                                                        const finalVal = !isNaN(parsed) && newVal.trim() !== '' ? parsed : newVal;
                                                                        if (finalVal !== val) {
                                                                            const updated = [...previewData];
                                                                            updated[i] = { ...updated[i], [key]: finalVal };
                                                                            setPreviewData(updated);
                                                                            setIsEdited(true);
                                                                        }
                                                                    }}
                                                                    style={{
                                                                        width: '100%', border: '1px solid transparent',
                                                                        borderRadius: 4, padding: '4px 6px', fontSize: 12,
                                                                        background: 'transparent', color: 'var(--text)',
                                                                        outline: 'none', minWidth: 60,
                                                                    }}
                                                                    onFocus={(e) => {
                                                                        e.target.style.border = '1px solid var(--primary)';
                                                                        e.target.style.background = 'var(--primary-light)';
                                                                    }}
                                                                    onBlurCapture={(e) => {
                                                                        e.target.style.border = '1px solid transparent';
                                                                        e.target.style.background = 'transparent';
                                                                    }}
                                                                />
                                                            </td>
                                                        ))}
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                </>
                            )}
                        </div>
                    )}
                </div>

                {/* Error */}
                {error && (
                    <div style={{
                        background: 'var(--danger-light)', color: '#b91c1c',
                        padding: '10px 16px', borderRadius: 10, fontSize: 13,
                        fontWeight: 600, marginBottom: 16,
                    }}>{error}</div>
                )}

                {/* Action Buttons */}
                {file && previewData && (
                    <button
                        onClick={handleCompute}
                        disabled={isLoading}
                        className="btn-primary"
                        style={{
                            width: '100%', padding: '14px 24px', fontSize: 16,
                            display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10,
                            opacity: isLoading ? 0.7 : 1,
                        }}
                    >
                        {isLoading ? (
                            <>
                                <div className="spinner spinner-sm" style={{ borderTopColor: '#fff', borderColor: 'rgba(255,255,255,0.3)' }} />
                                {loadingMsg}
                            </>
                        ) : (
                            <>
                                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M13 10V3L4 14h7v7l9-11h-7z" />
                                </svg>
                                Optimize Routes
                            </>
                        )}
                    </button>
                )}

                {/* Features strip */}
                <div style={{
                    display: 'flex', justifyContent: 'center', gap: 32,
                    marginTop: 40, paddingTop: 24,
                    borderTop: '1px solid var(--border-light)',
                }}>
                    {[
                        { icon: "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z", label: "AI Optimized" },
                        { icon: "M13 10V3L4 14h7v7l9-11h-7z", label: "Live Traffic" },
                        { icon: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z", label: "Real-time ETAs" },
                    ].map((feat, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--primary)" strokeWidth="2">
                                <path strokeLinecap="round" strokeLinejoin="round" d={feat.icon} />
                            </svg>
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
                    <div className="spinner" style={{ width: 48, height: 48, marginBottom: 16 }} />
                    <p style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)' }}>{loadingMsg}</p>
                    <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>This may take a moment...</p>
                </div>
            )}
        </div>
    );
};

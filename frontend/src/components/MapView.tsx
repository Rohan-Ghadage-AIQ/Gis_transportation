import React, { useEffect, useRef, useState } from 'react';
import * as maptilersdk from '@maptiler/sdk';
import type { RouteResults } from '../types/api';

interface MapViewProps {
    results: RouteResults;
}

export const MapView: React.FC<MapViewProps> = ({ results }) => {
    const mapContainer = useRef<HTMLDivElement>(null);
    const map = useRef<maptilersdk.Map | null>(null);
    const markersRef = useRef<Map<number, maptilersdk.Marker[]>>(new Map());

    // State to track which vehicles are visible (all visible by default)
    const [visibleVehicles, setVisibleVehicles] = useState<Set<number>>(
        new Set(results.vehicles.map(v => v.vehicle_id))
    );

    // Toggle traffic color mode
    const [showTrafficColors, setShowTrafficColors] = useState(true);

    // Collapsible legend state
    const [legendOpen, setLegendOpen] = useState(false);

    // Toggle vehicle visibility
    const toggleVehicleVisibility = (vehicleId: number) => {
        setVisibleVehicles(prev => {
            const newSet = new Set(prev);
            if (newSet.has(vehicleId)) {
                newSet.delete(vehicleId);
            } else {
                newSet.add(vehicleId);
            }
            return newSet;
        });
    };

    useEffect(() => {
        if (!mapContainer.current || map.current) return;

        const apiKey = import.meta.env.VITE_MAPTILER_KEY;
        if (!apiKey) {
            console.error('MapTiler API key is missing');
            return;
        }

        maptilersdk.config.apiKey = apiKey;

        // Initialize map centered on warehouse
        const { warehouse } = results.summary;
        map.current = new maptilersdk.Map({
            container: mapContainer.current,
            style: maptilersdk.MapStyle.STREETS,
            center: [warehouse.lon, warehouse.lat],
            zoom: 10,
        });

        map.current.on('load', () => {
            if (!map.current) return;

            // Add warehouse marker
            new maptilersdk.Marker({ color: '#FF0000', scale: 1.5 })
                .setLngLat([warehouse.lon, warehouse.lat])
                .setPopup(
                    new maptilersdk.Popup().setHTML(
                        `<strong>${warehouse.name}</strong><br/>Depot`
                    )
                )
                .addTo(map.current);

            // Add routes and markers for each vehicle
            results.vehicles.forEach((vehicle) => {
                if (!map.current) return;

                // Add route line from GeoJSON geometry
                if (vehicle.route_geometry && vehicle.route_geometry.length > 0) {
                    vehicle.route_geometry.forEach((feature: any, idx: number) => {
                        if (!map.current) return;

                        // Determine segment color: use traffic color if enabled, else vehicle color
                        const trafficFactor = feature?.properties?.traffic_factor ?? 1.0;
                        const trafficColor = feature?.properties?.traffic_color ?? '#22C55E';
                        const segmentColor = (showTrafficColors && trafficFactor > 1.0)
                            ? trafficColor
                            : vehicle.color;

                        // Add source for this route segment
                        map.current.addSource(`route-${vehicle.vehicle_id}-${idx}`, {
                            type: 'geojson',
                            data: feature
                        });

                        // Add layer to display the route
                        map.current.addLayer({
                            id: `route-${vehicle.vehicle_id}-${idx}`,
                            type: 'line',
                            source: `route-${vehicle.vehicle_id}-${idx}`,
                            layout: {
                                'line-join': 'round',
                                'line-cap': 'round',
                            },
                            paint: {
                                'line-color': segmentColor,
                                'line-width': trafficFactor > 1.5 ? 7 : 5,
                                'line-opacity': 0.95,
                            },
                        });

                        // Add arrow symbols to show direction
                        map.current.addLayer({
                            id: `route-arrows-${vehicle.vehicle_id}-${idx}`,
                            type: 'symbol',
                            source: `route-${vehicle.vehicle_id}-${idx}`,
                            layout: {
                                'symbol-placement': 'line',
                                'symbol-spacing': 100,
                                'icon-image': 'arrow',
                                'icon-size': 0.5,
                                'icon-rotation-alignment': 'map',
                                'icon-allow-overlap': true,
                                'icon-ignore-placement': true,
                            },
                            paint: {
                                'icon-opacity': 0.8,
                            },
                        });
                    });
                }

                // Add station markers and store references
                const vehicleMarkers: maptilersdk.Marker[] = [];
                vehicle.stations.forEach((station, index) => {
                    if (!map.current) return;

                    const el = document.createElement('div');
                    el.className = 'station-marker';
                    el.style.backgroundColor = vehicle.color;
                    el.style.width = '24px';
                    el.style.height = '24px';
                    el.style.borderRadius = '50%';
                    el.style.border = '3px solid white';
                    el.style.cursor = 'pointer';
                    el.style.boxShadow = '0 2px 4px rgba(0,0,0,0.3)';

                    const marker = new maptilersdk.Marker({ element: el })
                        .setLngLat([station.lon, station.lat])
                        .setPopup(
                            new maptilersdk.Popup({ offset: 25 }).setHTML(
                                `<div style="color: #000;">
                  <strong>Vehicle ${vehicle.vehicle_id}</strong><br/>
                  ${station.station_id}<br/>
                  Arrival: ${station.arrival_time}<br/>
                  Status: <span style="color: ${station.status === 'IDEAL'
                                    ? 'green'
                                    : station.status === 'IN BUFFER'
                                        ? 'orange'
                                        : 'red'
                                }">${station.status}</span>
                </div>`
                            )
                        )
                        .addTo(map.current);

                    vehicleMarkers.push(marker);
                });

                // Store markers for this vehicle
                markersRef.current.set(vehicle.vehicle_id, vehicleMarkers);
            });
        });

        return () => {
            map.current?.remove();
            map.current = null;
        };
    }, [results, showTrafficColors]);

    // Control layer and marker visibility based on visibleVehicles state
    useEffect(() => {
        if (!map.current) return;

        results.vehicles.forEach((vehicle) => {
            const isVisible = visibleVehicles.has(vehicle.vehicle_id);
            const visibility = isVisible ? 'visible' : 'none';

            // Hide/show route lines and arrows
            vehicle.route_geometry?.forEach((_, idx) => {
                try {
                    map.current?.setLayoutProperty(
                        `route-${vehicle.vehicle_id}-${idx}`,
                        'visibility',
                        visibility
                    );
                    map.current?.setLayoutProperty(
                        `route-arrows-${vehicle.vehicle_id}-${idx}`,
                        'visibility',
                        visibility
                    );
                } catch (e) {
                    // Layer might not exist yet
                }
            });

            // Hide/show markers
            const markers = markersRef.current.get(vehicle.vehicle_id) || [];
            markers.forEach(marker => {
                const el = marker.getElement();
                el.style.display = isVisible ? 'block' : 'none';
            });
        });
    }, [visibleVehicles, results.vehicles]);

    return (
        <div style={{ position: 'relative', width: '100%', height: '100%' }}>
            <div ref={mapContainer} className="map-container" />

            {/* Collapsible Legend */}
            <div style={{
                position: 'absolute', top: 16, right: 16,
                background: 'var(--bg)', borderRadius: 12,
                boxShadow: 'var(--shadow-lg)', border: '1px solid var(--border)',
                maxWidth: 240, overflow: 'hidden',
            }}>
                {/* Toggle header — always visible */}
                <button
                    onClick={() => setLegendOpen(prev => !prev)}
                    style={{
                        width: '100%', display: 'flex', alignItems: 'center',
                        justifyContent: 'space-between', padding: '10px 14px',
                        background: 'none', border: 'none', cursor: 'pointer',
                    }}
                >
                    <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text)' }}>
                        Vehicle Routes
                    </span>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
                        stroke="var(--text-muted)" strokeWidth="2.5"
                        style={{
                            transition: 'transform 0.25s ease',
                            transform: legendOpen ? 'rotate(180deg)' : 'rotate(0)',
                        }}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                </button>

                {/* Collapsible body */}
                {legendOpen && (
                    <div style={{ padding: '0 14px 14px' }}>
                        {/* Show All / Hide All */}
                        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
                            <button
                                onClick={() => setVisibleVehicles(new Set(results.vehicles.map(v => v.vehicle_id)))}
                                style={{
                                    flex: 1, fontSize: 11, padding: '4px 8px', border: 'none', borderRadius: 6,
                                    background: 'var(--primary-light)', color: 'var(--primary-dark)',
                                    fontWeight: 600, cursor: 'pointer'
                                }}>Show All</button>
                            <button
                                onClick={() => setVisibleVehicles(new Set())}
                                style={{
                                    flex: 1, fontSize: 11, padding: '4px 8px', border: 'none', borderRadius: 6,
                                    background: 'var(--surface)', color: 'var(--text-muted)',
                                    fontWeight: 600, cursor: 'pointer'
                                }}>Hide All</button>
                        </div>

                        {/* Vehicle list */}
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 220, overflowY: 'auto' }}>
                            {results.vehicles.map((vehicle) => (
                                <label key={vehicle.vehicle_id} style={{
                                    display: 'flex', alignItems: 'center', fontSize: 12,
                                    cursor: 'pointer', padding: '3px 6px', borderRadius: 6,
                                }}
                                    onMouseOver={e => (e.currentTarget.style.background = 'var(--primary-light)')}
                                    onMouseOut={e => (e.currentTarget.style.background = 'transparent')}
                                >
                                    <input type="checkbox"
                                        checked={visibleVehicles.has(vehicle.vehicle_id)}
                                        onChange={() => toggleVehicleVisibility(vehicle.vehicle_id)}
                                        style={{ marginRight: 6, cursor: 'pointer', accentColor: 'var(--primary)' }} />
                                    <div style={{ width: 10, height: 10, borderRadius: '50%', marginRight: 6, background: vehicle.color, flexShrink: 0 }} />
                                    <span style={{ color: 'var(--text)' }}>V{vehicle.vehicle_id} ({vehicle.stations.length})</span>
                                </label>
                            ))}
                        </div>

                        {/* Warehouse */}
                        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border-light)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', fontSize: 12 }}>
                                <div style={{ width: 10, height: 10, borderRadius: '50%', background: '#DC2626', marginRight: 6 }} />
                                <span style={{ color: 'var(--text)' }}>Warehouse</span>
                            </div>
                        </div>

                        {/* Traffic Legend */}
                        <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid var(--border-light)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text)' }}>Live Traffic</span>
                                <button onClick={() => setShowTrafficColors(prev => !prev)} style={{
                                    fontSize: 10, padding: '2px 8px', border: 'none', borderRadius: 4, fontWeight: 700, cursor: 'pointer',
                                    background: showTrafficColors ? 'var(--success-light)' : 'var(--surface)',
                                    color: showTrafficColors ? '#15803d' : 'var(--text-muted)',
                                }}>{showTrafficColors ? 'ON' : 'OFF'}</button>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, fontSize: 11, color: 'var(--text-muted)' }}>
                                {[
                                    { color: '#22C55E', label: 'Free Flow (≤1.1×)' },
                                    { color: '#EAB308', label: 'Light (1.1×–1.5×)' },
                                    { color: '#F97316', label: 'Moderate (1.5×–2.0×)' },
                                    { color: '#DC2626', label: 'Heavy (>2.0×)' },
                                ].map(item => (
                                    <div key={item.color} style={{ display: 'flex', alignItems: 'center' }}>
                                        <div style={{ width: 18, height: 5, borderRadius: 3, background: item.color, marginRight: 8 }} />
                                        {item.label}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};
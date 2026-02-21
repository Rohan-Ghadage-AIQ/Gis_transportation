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
        <div className="relative w-full h-full">
            <div ref={mapContainer} className="map-container" />

            {/* Legend with Checkboxes */}
            <div className="absolute top-4 right-4 bg-white rounded-lg shadow-lg p-4 max-w-xs">
                <h3 className="text-gray-900 font-semibold mb-3">Vehicle Routes</h3>

                {/* Show All / Hide All Buttons */}
                <div className="flex gap-2 mb-3">
                    <button
                        onClick={() => setVisibleVehicles(new Set(results.vehicles.map(v => v.vehicle_id)))}
                        className="flex-1 text-xs px-2 py-1 bg-blue-100 hover:bg-blue-200 text-blue-700 rounded transition-colors"
                    >
                        Show All
                    </button>
                    <button
                        onClick={() => setVisibleVehicles(new Set())}
                        className="flex-1 text-xs px-2 py-1 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded transition-colors"
                    >
                        Hide All
                    </button>
                </div>

                {/* Vehicle Checkboxes */}
                <div className="space-y-2">
                    {results.vehicles.map((vehicle) => (
                        <label
                            key={vehicle.vehicle_id}
                            className="flex items-center text-sm cursor-pointer hover:bg-gray-50 p-1 rounded transition-colors"
                        >
                            <input
                                type="checkbox"
                                checked={visibleVehicles.has(vehicle.vehicle_id)}
                                onChange={() => toggleVehicleVisibility(vehicle.vehicle_id)}
                                className="mr-2 cursor-pointer"
                            />
                            <div
                                className="w-4 h-4 rounded-full mr-2"
                                style={{ backgroundColor: vehicle.color }}
                            />
                            <span className="text-gray-700">
                                Vehicle {vehicle.vehicle_id} ({vehicle.stations.length} stops)
                            </span>
                        </label>
                    ))}
                </div>

                {/* Warehouse Legend */}
                <div className="mt-3 pt-3 border-t border-gray-200">
                    <div className="flex items-center text-sm">
                        <div className="w-4 h-4 rounded-full bg-red-600 mr-2" />
                        <span className="text-gray-700">Warehouse</span>
                    </div>
                </div>

                {/* Traffic Legend */}
                <div className="mt-3 pt-3 border-t border-gray-200">
                    <div className="flex items-center justify-between mb-2">
                        <span className="text-gray-900 font-semibold text-sm">Live Traffic</span>
                        <button
                            onClick={() => setShowTrafficColors(prev => !prev)}
                            className={`text-xs px-2 py-0.5 rounded transition-colors ${showTrafficColors
                                    ? 'bg-green-100 text-green-700'
                                    : 'bg-gray-100 text-gray-500'
                                }`}
                        >
                            {showTrafficColors ? 'ON' : 'OFF'}
                        </button>
                    </div>
                    <div className="space-y-1 text-xs text-gray-600">
                        <div className="flex items-center">
                            <div className="w-6 h-2 rounded mr-2" style={{ backgroundColor: '#22C55E' }} />
                            Free Flow (≤1.1×)
                        </div>
                        <div className="flex items-center">
                            <div className="w-6 h-2 rounded mr-2" style={{ backgroundColor: '#EAB308' }} />
                            Light (1.1×–1.5×)
                        </div>
                        <div className="flex items-center">
                            <div className="w-6 h-2 rounded mr-2" style={{ backgroundColor: '#F97316' }} />
                            Moderate (1.5×–2.0×)
                        </div>
                        <div className="flex items-center">
                            <div className="w-6 h-2 rounded mr-2" style={{ backgroundColor: '#DC2626' }} />
                            Heavy (&gt;2.0×)
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};
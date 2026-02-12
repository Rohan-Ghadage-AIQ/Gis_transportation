import React, { useEffect, useRef } from 'react';
import * as maptilersdk from '@maptiler/sdk';
import type { RouteResults } from '../types/api';

interface MapViewProps {
    results: RouteResults;
}

export const MapView: React.FC<MapViewProps> = ({ results }) => {
    const mapContainer = useRef<HTMLDivElement>(null);
    const map = useRef<maptilersdk.Map | null>(null);

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
                    // vehicle.route_geometry is an array of GeoJSON features
                    // Each feature has a MultiLineString geometry
                    vehicle.route_geometry.forEach((feature: any, idx: number) => {
                        if (!map.current) return;

                        // Add source for this route segment
                        map.current.addSource(`route-${vehicle.vehicle_id}-${idx}`, {
                            type: 'geojson',
                            data: feature
                        });

                        // Add layer to display the route with arrows
                        map.current.addLayer({
                            id: `route-${vehicle.vehicle_id}-${idx}`,
                            type: 'line',
                            source: `route-${vehicle.vehicle_id}-${idx}`,
                            layout: {
                                'line-join': 'round',
                                'line-cap': 'round',
                            },
                            paint: {
                                'line-color': vehicle.color,
                                'line-width': 5,
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


                // Add station markers
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

                    new maptilersdk.Marker({ element: el })
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
                });
            });
        });

        return () => {
            map.current?.remove();
            map.current = null;
        };
    }, [results]);

    return (
        <div className="relative w-full h-full">
            <div ref={mapContainer} className="map-container" />

            {/* Legend */}
            <div className="absolute top-4 right-4 bg-white rounded-lg shadow-lg p-4 max-w-xs">
                <h3 className="text-gray-900 font-semibold mb-2">Vehicle Routes</h3>
                <div className="space-y-1">
                    {results.vehicles.map((vehicle) => (
                        <div key={vehicle.vehicle_id} className="flex items-center text-sm">
                            <div
                                className="w-4 h-4 rounded-full mr-2"
                                style={{ backgroundColor: vehicle.color }}
                            />
                            <span className="text-gray-700">
                                Vehicle {vehicle.vehicle_id} ({vehicle.stations.length} stops)
                            </span>
                        </div>
                    ))}
                </div>
                <div className="mt-3 pt-3 border-t border-gray-200">
                    <div className="flex items-center text-sm">
                        <div className="w-4 h-4 rounded-full bg-red-600 mr-2" />
                        <span className="text-gray-700">Warehouse</span>
                    </div>
                </div>
            </div>
        </div>
    );
};
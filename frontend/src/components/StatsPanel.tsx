import React from 'react';
import type { RouteResults } from '../types/api';

interface StatsPanelProps {
    results: RouteResults;
}

export const StatsPanel: React.FC<StatsPanelProps> = ({ results }) => {
    const { summary, vehicles } = results;

    return (
        <div className="h-full overflow-y-auto bg-gray-900 p-6">
            <h2 className="text-3xl font-bold text-white mb-6">Route Statistics</h2>

            {/* Summary Cards */}
            <div className="grid grid-cols-1 gap-4 mb-6">
                <div className="bg-gradient-to-br from-blue-600 to-blue-700 rounded-lg p-6 shadow-lg">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-blue-200 text-sm font-medium">Total Distance</p>
                            <p className="text-white text-3xl font-bold">
                                {summary.total_distance.toFixed(2)} km
                            </p>
                        </div>
                        <svg className="w-12 h-12 text-blue-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
                        </svg>
                    </div>
                </div>

                <div className="bg-gradient-to-br from-green-600 to-green-700 rounded-lg p-6 shadow-lg">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-green-200 text-sm font-medium">Total Cost</p>
                            <p className="text-white text-3xl font-bold">
                                ₹{summary.total_cost.toFixed(2)}
                            </p>
                        </div>
                        <svg className="w-12 h-12 text-green-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                </div>

                <div className="bg-gradient-to-br from-purple-600 to-purple-700 rounded-lg p-6 shadow-lg">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-purple-200 text-sm font-medium">Total Parcels</p>
                            <p className="text-white text-3xl font-bold">
                                {summary.total_parcels}
                            </p>
                        </div>
                        <svg className="w-12 h-12 text-purple-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4" />
                        </svg>
                    </div>
                </div>

                <div className="bg-gradient-to-br from-orange-600 to-orange-700 rounded-lg p-6 shadow-lg">
                    <div className="flex items-center justify-between">
                        <div>
                            <p className="text-orange-200 text-sm font-medium">Active Fleets</p>
                            <p className="text-white text-3xl font-bold">
                                {summary.total_fleets}
                            </p>
                        </div>
                        <svg className="w-12 h-12 text-orange-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2" />
                        </svg>
                    </div>
                </div>
            </div>

            {/* Vehicle Details */}
            <div className="space-y-4">
                <h3 className="text-xl font-semibold text-white mb-4">Vehicle Breakdown</h3>
                {vehicles.map((vehicle) => (
                    <details
                        key={vehicle.vehicle_id}
                        className="bg-gray-800 rounded-lg shadow-lg overflow-hidden group"
                    >
                        <summary className="cursor-pointer p-4 hover:bg-gray-750 transition-colors">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center">
                                    <div
                                        className="w-6 h-6 rounded-full mr-3"
                                        style={{ backgroundColor: vehicle.color }}
                                    />
                                    <span className="text-white font-semibold">
                                        Vehicle {vehicle.vehicle_id}
                                    </span>
                                    {results.rerouted_vehicles?.includes(vehicle.vehicle_id) && (
                                        <span className="ml-3 px-2 py-0.5 bg-amber-500 text-white text-[10px] font-bold rounded-full animate-pulse">
                                            REROUTED
                                        </span>
                                    )}
                                </div>
                                <div className="flex items-center space-x-4 text-sm">
                                    <span className="text-gray-400">
                                        {vehicle.stations.length} stops
                                    </span>
                                    <span className="text-gray-400">
                                        {vehicle.total_distance.toFixed(2)} km
                                    </span>
                                </div>
                            </div>
                        </summary>

                        <div className="p-4 bg-gray-750 border-t border-gray-700">
                            <div className="grid grid-cols-2 gap-4 mb-4">
                                <div>
                                    <p className="text-gray-400 text-sm">Distance</p>
                                    <p className="text-white font-semibold">
                                        {vehicle.total_distance?.toFixed(2) || '0.00'} km
                                    </p>
                                </div>
                                <div>
                                    <p className="text-gray-400 text-sm">Cost</p>
                                    <p className="text-white font-semibold">
                                        ₹{vehicle.cost?.toFixed(2) || '0.00'}
                                    </p>
                                </div>
                                <div>
                                    <p className="text-gray-400 text-sm">Weight</p>
                                    <p className="text-white font-semibold">
                                        {vehicle.total_weight || 0}kg / {vehicle.capacity || 0}kg
                                    </p>
                                </div>
                                <div>
                                    <p className="text-gray-400 text-sm">Utilization</p>
                                    <p className="text-white font-semibold">
                                        {vehicle.utilization}%
                                    </p>
                                </div>
                                <div>
                                    <p className="text-gray-400 text-sm">Clock-in</p>
                                    <p className="text-white font-semibold">{vehicle.clock_in}</p>
                                </div>
                                <div>
                                    <p className="text-gray-400 text-sm">Clock-out</p>
                                    <p className="text-white font-semibold">{vehicle.clock_out || 'N/A'}</p>
                                </div>
                                <div>
                                    <p className="text-gray-400 text-sm">Work Duration</p>
                                    <p className="text-white font-semibold">
                                        {vehicle.work_duration} mins
                                    </p>
                                </div>
                            </div>

                            {/* Utilization Bar */}
                            <div className="mb-4">
                                <div className="flex justify-between text-sm text-gray-400 mb-1">
                                    <span>Capacity Utilization</span>
                                    <span>{vehicle.utilization}%</span>
                                </div>
                                <div className="w-full bg-gray-700 rounded-full h-2">
                                    <div
                                        className="h-2 rounded-full transition-all"
                                        style={{
                                            width: `${vehicle.utilization}%`,
                                            backgroundColor: vehicle.color,
                                        }}
                                    />
                                </div>
                            </div>

                            {/* Stations List */}
                            <div>
                                <p className="text-gray-400 text-sm mb-2">Stops:</p>
                                <div className="space-y-1 max-h-40 overflow-y-auto">
                                    {vehicle.stations.map((station, index) => (
                                        <div
                                            key={index}
                                            className="flex justify-between items-center text-sm bg-gray-800 p-2 rounded"
                                        >
                                            <span className="text-gray-300">{station.station_id}</span>
                                            <div className="flex items-center space-x-2">
                                                <span className="text-gray-400">{station.arrival_time}</span>
                                                <span
                                                    className={`px-2 py-1 rounded text-xs ${station.status === 'ON TIME'
                                                            ? 'bg-green-500/20 text-green-400'
                                                            : station.status === 'IN_BUFFER'
                                                                ? 'bg-blue-500/20 text-blue-400'
                                                                : station.status === 'LATE'
                                                                    ? 'bg-red-500/20 text-red-400'
                                                                    : 'bg-gray-500/20 text-gray-400'
                                                        }`}
                                                >
                                                    {station.status}
                                                </span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>
                    </details>
                ))}
            </div>

            {/* Undelivered Parcels Section */}
            {results.undelivered_parcels && results.undelivered_parcels.length > 0 && (
                <div className="mt-8">
                    <h3 className="text-xl font-semibold text-white mb-4">
                        Undelivered Parcels ({results.undelivered_parcels.length})
                    </h3>
                    <div className="bg-red-900/20 border border-red-500/50 rounded-lg p-4">
                        <p className="text-red-300 mb-3">
                            The following parcels could not be assigned to any vehicle:
                        </p>
                        <div className="space-y-2 max-h-60 overflow-y-auto">
                            {results.undelivered_parcels.map((parcel, index) => (
                                <div
                                    key={index}
                                    className="flex justify-between items-center bg-gray-800 p-3 rounded"
                                >
                                    <span className="text-white font-medium">
                                        Station {parcel.station_id}
                                    </span>
                                    <span className="text-gray-400 text-sm">
                                        {parcel.lat.toFixed(4)}, {parcel.lon.toFixed(4)}
                                    </span>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

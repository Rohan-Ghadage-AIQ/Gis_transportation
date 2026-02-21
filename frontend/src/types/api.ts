// API Response Types
export interface Station {
    station_id: string;
    lat: number;
    lon: number;
    arrival_time: string;
    status: string; // 'ON TIME', 'IN_BUFFER', or 'LATE'
}

export interface RouteGeometry {
    lat: number;
    lon: number;
}

export interface VehicleRoute {
    vehicle_id: number;
    stations: Station[];
    route_geometry: RouteGeometry[];
    total_distance: number;
    cost: number;
    total_weight: number;
    capacity: number;
    utilization: number;
    work_duration: number;
    color: string;
    clock_in: string;
    clock_out: string;
}

export interface Warehouse {
    lat: number;
    lon: number;
    name: string;
}

export interface Summary {
    total_distance: number;
    total_cost: number;
    total_parcels: number;
    total_fleets: number;
    warehouse: Warehouse;
}

export interface Parcel {
    station_id: string;
    lat: number;
    lon: number;
    vehicle_id: number;
    color: string;
}

export interface RouteResults {
    vehicles: VehicleRoute[];
    summary: Summary;
    parcels: Parcel[];
    undelivered_parcels: Array<{
        station_id: string;
        lat: number;
        lon: number;
    }>;
    rerouted_vehicles?: number[];
}

// Upload Response Types
export interface UploadResponse {
    status: string;
    message: string;
    data: Record<string, any>[];
    columns: string[];
    row_count: number;
}

export interface ComputeResponse {
    status: string;
    message: string;
    rerouted_vehicles?: number[];
}

export interface HealthResponse {
    status: string;
    message: string;
}

// Fleet Vehicle Types
export interface VehicleConfig {
    id?: number;
    name: string;
    capacity_kg: number;
    cost_per_km: number;
    shift_start: number;   // minutes from midnight
    shift_end: number;
}

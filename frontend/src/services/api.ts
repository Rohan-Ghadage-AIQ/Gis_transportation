import axios from 'axios';
import type { UploadResponse, ComputeResponse, RouteResults, VehicleConfig } from '../types/api';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

const api = axios.create({
    baseURL: API_URL,
    headers: {
        'Content-Type': 'application/json',
    },
});

export const apiService = {
    // Health check
    async healthCheck() {
        const response = await api.get('/api/health');
        return response.data;
    },

    // Upload file
    async uploadFile(file: File): Promise<UploadResponse> {
        const formData = new FormData();
        formData.append('file', file);

        const response = await api.post<UploadResponse>('/api/upload', formData, {
            headers: {
                'Content-Type': 'multipart/form-data',
            },
        });
        return response.data;
    },

    // Update data after editing
    async updateData(data: Record<string, any>[]): Promise<{ status: string; message: string }> {
        const response = await api.post('/api/update-data', { data });
        return response.data;
    },

    // Trigger computation
    async computeRoutes(): Promise<ComputeResponse> {
        const response = await api.post<ComputeResponse>('/api/compute');
        return response.data;
    },

    // Get results
    async getResults(): Promise<RouteResults> {
        const response = await api.get<RouteResults>('/api/results');
        return response.data;
    },

    // Refresh traffic and re-solve
    async refreshTraffic(): Promise<RouteResults> {
        const response = await api.post<RouteResults>('/api/refresh-traffic');
        return response.data;
    },

    // ── Fleet Management ──

    async getFleet(): Promise<VehicleConfig[]> {
        const response = await api.get<{ vehicles: VehicleConfig[] }>('/api/fleet');
        return response.data.vehicles;
    },

    async updateVehicle(vehicle: VehicleConfig): Promise<VehicleConfig> {
        const response = await api.put<{ status: string; vehicle: VehicleConfig }>('/api/fleet', vehicle);
        return response.data.vehicle;
    },

    async deleteVehicle(vehicleId: number): Promise<void> {
        await api.delete(`/api/fleet/${vehicleId}`);
    },

    // ── Auto Re-optimization ──

    async toggleAutoReoptimize(enabled: boolean): Promise<{ enabled: boolean; interval_seconds: number; last_run: string | null }> {
        const response = await api.post('/api/auto-reoptimize', { enabled });
        return response.data;
    },

    async getAutoReoptimizeStatus(): Promise<{ enabled: boolean; interval_seconds: number; last_run: string | null; last_rerouted: number[] }> {
        const response = await api.get('/api/auto-reoptimize/status');
        return response.data;
    },

    async reoptimize(): Promise<{ success: boolean; rerouted_vehicles: number[]; total_reoptimized: number }> {
        const response = await api.post('/api/reoptimize');
        return response.data;
    },

    // ── Chatbot ──

    async chat(message: string, history: { role: string; content: string }[] = []): Promise<string> {
        const response = await api.post<{ response: string }>('/api/chat', { message, history });
        return response.data.response;
    },
};

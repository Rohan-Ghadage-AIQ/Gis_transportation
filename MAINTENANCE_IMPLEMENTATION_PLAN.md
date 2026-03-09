# Maintenance Team Planning Module Implementation Plan

## Goal Description
The objective is to create a new "Maintenance Team Planning" module parallel to the existing logistics module in the `GisTransportation4` repository. The user requires that the existing AIQLogistics logic and components remain completely untouched. Instead, we will overlay a global toggle in the application to switch between "AIQLogistics" and "AIQ Maintenance Team Planning".

The new module will ingest an Excel file with two sheets:
- **Sheet 1 (Tasks):** `id`, `company name`, `address`, `maintainceService_time(min)`, `Maintance_AVailable_slots`
- **Sheet 2 (Technicians):** `id`, `Name of person`, `Shift Timing`

All technicians will start from a central "Office Location". The optimization will utilize the existing Google Route Optimization API structure, but separate endpoints and pages will be created to ensure full separation of concerns. Additionally, a configurable maintenance team size constraint (default 3) will be applied.

## Proposed Changes

### Global Layout & Routing (Frontend)

#### [MODIFY] frontend/src/App.tsx
- Wrap the existing routes in a new layout or add a global "Module Toggle" component (Top Navigation Bar or Sidebar).
- The toggle will have two states: `AIQLogistics` (default) and `AIQMaintenance Team Planning`.
- Add separate dedicated routes for the Maintenance module:
  - `/maintenance` (Upload/Planning step)
  - `/maintenance-results` (Optimization results)
- Existing routes (`/` and `/results`) remain untouched and tied to the AIQLogistics view.

#### [NEW] frontend/src/components/ModuleToggle.tsx (Optional)
- A simple UI component to switch the application context and navigate between `/` (Logistics) and `/maintenance` (Maintenance).

### Maintenance Frontend Module (Frontend)

#### [NEW] frontend/src/pages/MaintenanceUploadPage.tsx
- A completely separate upload page for Maintenance Planning.
- Handles the two-sheet Excel file parsing.
- Displays two tables: Maintenance Tasks, and Technicians (with shift timings).
- Allows office location configuration.
- **Includes a setting to adjust the "Team Size" (default 3) before computation.**
- Triggers the new `/api/maintenance/compute` endpoint with the selected team size.

#### [NEW] frontend/src/pages/MaintenanceResultsPage.tsx
- A specialized results dashboard for maintenance planning.
- Copies the `MapView` and `StatsPanel` concepts but displays "Technician Names" and distinct maintenance metrics instead of generic "Vehicles".

### Maintenance Backend Module (Backend)

We will not modify existing processing functions `main.py` directly where possible; we will add *new* endpoints, keeping existing backend logic pristine.

#### [MODIFY] backend/main.py
- Add new endpoints explicitly for maintenance:
  - `POST /api/maintenance/upload`: Parses the multi-sheet Excel file and returns JSON separately for Tasks and Technicians.
  - `POST /api/maintenance/compute`: Prepares a new `maintenance_station_map` table (to prevent interfering with the logistics `station_node_map`), processes dynamic shift logic for each technician, configures the fleet using the specified `team_size` limit, and calls the VRP solver.
  - `GET /api/maintenance/results`: Fetches from the maintenance-specific tables and formats vehicle data using "Technician Names".

#### [MODIFY] backend/database.py
- Create setup functions for a new table: `vector.maintenance_task_node_map`, ensuring the Logistics table `vector.station_node_map` is not dropped or altered during maintenance planning.
- Create insertion, retrieval, and fleet setup functions specific to the Maintenance module, ensuring the fleet setup limits the pool to the provided `team_size`.
- Ensure config files/constants contain a default for the Maintenance Team Size.

### Database Setup

#### [NEW] `vector.maintenance_task_node_map` table
- A separate PostGIS table modeled after `station_node_map` but for maintenance tasks, preventing data overlap between the two modules if used simultaneously.

## Verification Plan

### Automated Tests
- Ensure existing Logistics workflows still run perfectly by testing the base `/api/upload` and `/api/compute`.
- Unit test the multi-sheet Excel parsing for the new `/api/maintenance/upload` endpoint.
- Verify that compute calls with `team_size=3` accurately limit the fleet.

### Manual Verification
1. Open the application and verify the new Toggle exists and defaults to "AIQLogistics".
2. Test the existing Logistics flow to confirm it is unbroken.
3. Switch the Toggle to "AIQ Maintenance Team Planning".
4. Upload the sample maintenance dual-sheet Excel.
5. Verify the tasks and technicians are rendered in the new Maintenance UI.
6. Verify the "Team Size" defaults to 3 and can be updated securely.
7. Trigger computation and verify the Maintenance Results page renders Technician names correctly, adheres strictly to the team size constraint, and only queries the new maintenance tables.

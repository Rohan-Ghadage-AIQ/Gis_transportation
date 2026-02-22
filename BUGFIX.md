# Bug Fix: Vehicle Time Constraint Violations

## Problem

Parcels were being assigned arrival times **outside** their vehicle's operating hours. For example:
- **Vehicle 4** (shift 8:00 AM – 8:00 PM) had a parcel with arrival time **7:24 AM** (before shift start)
- **Vehicle 8** (shift 7:00 AM – 8:00 PM) had a parcel with `window_end` of **5:00 AM**

## Root Cause Analysis

**4 bugs** were identified in `backend/vrp_solver.py`:

### Bug 1: Parcel time windows ignored `window_start`

```python
# BEFORE — allowed arrival at time 0 (7 AM) for every parcel
time_dimension.CumulVar(index).SetRange(0, 840)
```

The parcel's `window_start` was fetched from the database but never used in the hard constraint. Every parcel could be visited as early as 7:00 AM regardless of its actual delivery window.

### Bug 2: Vehicle shift end was a soft constraint (not enforced)

```python
# BEFORE — vehicle could operate past its shift end (only penalized)
time_dimension.CumulVar(end_index).SetRange(start_avail, 840)
time_dimension.SetCumulVarSoftUpperBound(end_index, end_avail, 50000)
```

`SetRange(..., 840)` allowed any vehicle to operate until 9:00 PM. The actual shift end was only a soft penalty, easily overridden by the solver to avoid dropping parcels.

### Bug 3: Duplicate soft upper bounds (OR-Tools silent overwrite)

```python
# BEFORE — second call silently overwrites the first
time_dimension.SetCumulVarSoftUpperBound(index, preferred_time, 5000)
time_dimension.SetCumulVarSoftUpperBound(index, deadline, 100000000)
```

OR-Tools only retains the **last** `SetCumulVarSoftUpperBound` call per variable. The preferred-time penalty (5000) was silently discarded.

### Bug 4: Hardcoded time dimension maximum

```python
# BEFORE — hardcoded value didn't adapt to vehicle config
routing.AddDimension(time_callback_index, 60, 840, False, 'Time')
```

The `840` max was hardcoded instead of being derived from the actual vehicle shift configuration.

---

## Fix Applied

### Fix 1: Enforce parcel time windows as hard constraints
```python
# AFTER
ws, deadline = node_windows[i]
time_dimension.CumulVar(index).SetRange(ws, deadline)  # Hard constraint
preferred_time = max(ws, deadline - 60)
time_dimension.SetCumulVarSoftUpperBound(index, preferred_time, 5000)  # Single soft bound
```

### Fix 2: Make vehicle shift end a hard constraint
```python
# AFTER
time_dimension.CumulVar(end_index).SetRange(start_avail, end_avail)  # Hard constraint
```

### Fix 3: Remove duplicate soft upper bound
Only one `SetCumulVarSoftUpperBound` call per variable (included in Fix 1 above).

### Fix 4: Dynamic time dimension maximum
```python
# AFTER
max_shift = max(end for _, end in vehicle_times)
routing.AddDimension(time_callback_index, 60, max_shift, False, 'Time')
```

### Additional: Post-solution validation logging
Added a validation pass that prints each parcel's arrival time alongside its vehicle's shift window for easy verification in the console.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/vrp_solver.py` | Fixed time window constraints (lines 96–127), added validation (lines 299–312) |

## Impact

- Parcels will **no longer** be scheduled outside vehicle operating hours
- Parcels that genuinely cannot fit any vehicle's time window will appear as **unassigned** instead of being silently scheduled at invalid times
- If too many parcels become unassigned, widen vehicle shift windows or add more vehicles in the `vehicle_times` configuration

---

# Bug Fix: 13 Parcels Dropped (Distance Matrix Duplicate Node Bug)

## Problem

After fixing the time constraint violations above, only **43 out of 56** parcels were being delivered. The remaining 13 parcels were marked as "unassigned" even though they had valid coordinates and were successfully snapped to the road network.

## Root Cause Analysis

**1 critical bug** was identified in `backend/vrp_solver.py`:

### Bug: Distance matrix lost stations sharing the same road node

```python
# BEFORE — dict overwrites duplicate keys
node_to_idx = {node: i for i, node in enumerate(nodes_in_system)}
```

Multiple stations can snap to the **same** road node (e.g., two nearby addresses both map to road node `99999`). The `node_to_idx` dictionary only keeps the **last** station for each road node, silently discarding earlier ones.

**Result**: Discarded stations had all distances set to `1,000,000` (unreachable), so the solver dropped them.

**Evidence from logs**:
- `57 nodes` in solver (56 stations + 1 depot)
- Only `44 unique` road nodes → `1,892 entries` (44 × 43)
- `1,357 MISSING entries` = the distance pairs for the 13 overwritten stations

### Secondary issues fixed

- **`SetFixedCostOfVehicle(10000)`** was called **twice** per vehicle (in both the time and capacity loops), discouraging the solver from using all 10 vehicles
- **Drop penalty** of `1,000,000` was too low relative to fixed vehicle costs, making it cheaper to drop parcels than to add a vehicle
- **`randomize_station_attributes`** (in `database.py`) could generate `window_end = 0` (7:00 AM deadline), making delivery physically impossible

---

## Fix Applied

### Fix 1: Build distance matrix by station index (not road node lookup)
```python
# AFTER — iterate over all station pairs, look up by their road nodes
for i in range(size):
    for j in range(size):
        if i == j:
            continue
        road_node_i = nodes_in_system[i]
        road_node_j = nodes_in_system[j]
        if road_node_i == road_node_j:
            dist_matrix[i][j] = 0  # Same road node = zero distance
        elif (road_node_i, road_node_j) in dist_dict:
            dist_matrix[i][j] = int(float(dist_dict[(road_node_i, road_node_j)]))
```

### Fix 2: Balanced constraint tuning
- **Parcel deadlines** → soft constraints (late delivery preferred over dropping)
- **Vehicle shift end** → hard limit with 60-min overtime buffer + soft penalty at actual shift end
- **Fixed vehicle cost** reduced `10,000 → 2,000` (encourages using all vehicles)
- **Drop penalty** increased `1,000,000 → 10,000,000` (makes dropping virtually impossible)
- **Removed duplicate** `SetFixedCostOfVehicle` / `AddVariableMinimizedByFinalizer` calls

### Fix 3: Minimum delivery window in randomization (`database.py`)
- Shift 1 minimum `window_end` raised from `0 → 60` (8:00 AM instead of 7:00 AM)
- Shift 2 minimum `window_end` raised from `180 → 240` (11:00 AM instead of 10:00 AM)

---

## Files Changed

| File | Change |
|------|--------|
| `backend/vrp_solver.py` | Fixed distance matrix building (lines 52–75), rebalanced constraints (lines 107–146) |
| `backend/database.py` | Fixed minimum `window_end` in `randomize_station_attributes` (lines 173–183) |

## Impact

- All **56 parcels** are now delivered (previously only 43)
- All **10 vehicles** are utilized (previously only 6)
- No more "MISSING distance matrix entries" warnings
- Stations sharing the same road node are handled correctly

---

# Bug Fix: Delivery Report Status Logic & Formatting

## Problem

1. **Shift Timings Discrepancy**: The Excel report showed default 6 AM - 6 PM shifts for all vehicles, contradicting the actual solver configuration (e.g., Vehicle 1 starts at 09:00).
2. **Confusing "IN BUFFER" Status**: Parcels delivered within the last hour of their window were labeled "IN BUFFER", which was confusing alongside "ON TIME".
3. **Disordered Report**: The rows in the Excel report were not sorted chronologically, making it hard to track the route.

## Fix Applied

### Fix 1: Synced Vehicle Shifts
Updated `report_generator.py` to use the exact vehicle shift definitions from `vrp_solver.py`.
- **Before**: Hardcoded default list.
- **After**: Synced list matches solver (e.g., V1: 09:00 - 18:00).

### Fix 2: Refined Status Logic
Changed the logic for "IN BUFFER" vs "ON TIME" to be more intuitive:
- **ON TIME**: Delivery is within the window (0-59 mins early).
- **IN BUFFER**: Delivery is significantly early (> 1 hour early).
- **LATE**: Delivery is after the window end.

### Fix 3: Chronological Sorting
Updated the SQL query in `report_generator.py` to sort by `Arrival Time`.
```sql
ORDER BY s.vehicle_id, s.arrival_time
```

### Fix 4: Shift-Wise Summary
Added a new section at the bottom of the report to group parcels by their assigned shift (e.g., 07:00-10:00, 10:00-18:00), making it easy to verify shift adherence.

## Files Changed

| File | Change |
|------|--------|
| `backend/report_generator.py` | Updated shift definitions, status logic, sorting, and added summary section |
| `backend/vrp_solver.py` | Updated internal status string to match report terminology |

---

# Bug Fix: Unrealistic Travel Times & Unit Mismatch

## Problem

Vehicle arrival times were drastically early and logically impossible. For example, a vehicle would travel 15km through Mumbai city traffic in just 11 minutes (starting at 08:00 AM and arriving at 08:11 AM).

## Root Cause Analysis

**1 fundamental logic bug** was identified in `backend/vrp_solver.py`:

### Bug: Distance matrix unit interpreted as meters, while values were seconds

The `distance_matrix` table stores travel time in **seconds** (derived from `cost_s` or `live_cost_s` in `vector.road_maharashtra`). However, the solver was treating these values as **meters** and applying a conversion formula:

```python
# BEFORE
travel_time = dist_matrix[from_node][to_node] / 666  # Assumed meters -> minutes at 40km/h
```

Because the input was already seconds, dividing a 30-minute trip (1800 seconds) by 666 resulted in ~2.7 minutes of travel time. This made every route appear ~10x faster than reality and allowed the solver to pack too many deliveries into a single route.

## Fix Applied

### Fix 1: Corrected Travel Time Conversion
Converted the time callback to treat distance matrix values as seconds and divide by 60 to get minutes.

```python
# AFTER
travel_time = dist_matrix[from_node][to_node] / 60  # seconds -> minutes
```

### Fix 2: Road-Length Based Distance Calculation
Previously, `distance_km` was calculated by summing the seconds in the distance matrix and dividing by 1000, which produced meaningless "km" values.
- **After**: The system now queries the actual road geometry length (`ST_Length(geom::geography)`) for each route segment to calculate high-precision kilometer totals.

## Impact

- **Realistic Schedules**: Arrival times now accurately reflect real-world travel durations (seconds to minutes).
- **Correct Route Density**: The solver no longer over-packs vehicles by underestimating travel time.
- **Precise Distance Reporting**: Total km traveled now matches the actual road paths visualized on the map.

---

# Bug Fix: Vehicle Shift Cross-Midnight Logic

## Problem

Vehicles with overnight shifts (e.g., 8:00 AM to 01:04 AM) were having their routes truncated or reset. The solver would see the `01:04` end time as being numerically smaller than the `08:00` start time and flag it as an error, resetting the vehicle to a default 9-hour window.

## Root Cause Analysis

The solver was comparing relative minutes from midnight on the *same day*.
- `08:00 AM` = 480 minutes
- `01:04 AM` = 64 minutes
- Since `64 < 480`, the logic `end_avail < start_avail` triggered a manual fix that overwrote the user's configuration.

## Fix Applied

### Fix 1: Temporal Normalization
Implemented a normalization step during vehicle initialization in `backend/vrp_solver.py`:

```python
# If end is numerically smaller than start, it crosses midnight.
# Add 1440 minutes (24 hours) to the end time to offset it to the next day.
if end < start:
    end += 1440
```

### Fix 2: Dynamic Dimension Scaling
Updated the `absolute_max` calculation for the solver's Time dimension to ensure it spans the full duration of these extended multi-day shifts.

## Impact

- **Full Shift Utilization**: Vehicles can now correctly be assigned deliveries late into the night and early the next morning.
- **Accurate Next-Day Arrival**: The UI correctly displays these arrival times with a **"(+1 Day)"** indicator, ensuring the user and senior stakeholders see realistic schedules.



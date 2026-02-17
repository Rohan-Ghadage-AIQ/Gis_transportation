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

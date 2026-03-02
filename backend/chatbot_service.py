"""
Chatbot service for VRP analytics using Google Gemini API.
Answers questions ONLY from the system's route optimization data.
"""

import os
from google import genai
from google.genai import types
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv

load_dotenv()

# Configure Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

SYSTEM_PROMPT = """You are an AI analytics assistant for a Vehicle Routing Optimization system used by a logistics company in Maharashtra, India.

RULES:
1. Answer ONLY from the data provided below. Do NOT use external knowledge.
2. If asked something not in the data, say: "I can only answer questions about the current delivery plan data."
3. Be concise and professional. Use bullet points for lists.
4. Use ₹ (Indian Rupees) for currency values.
5. Format numbers clearly (e.g., "89.2 km", "₹1,078", "92.3%").
6. When mentioning vehicles, use "Vehicle X" format.
7. If asked to compare, present a clear side-by-side comparison.
8. Mention delivery statuses as: ✅ ON_TIME, ⏰ LATE, 🟡 IN_BUFFER.
9. For weather, use: 🌧️ for rain, ☀️ for clear.
10. Keep responses under 200 words unless the user asks for detailed breakdown.

DATA CONTEXT:
{context}
"""


def build_data_context(results_data: Dict[str, Any], uploaded_data_summary: Optional[Dict] = None) -> str:
    """Build a text summary of the current VRP results for Gemini context."""
    if not results_data or not results_data.get("vehicles"):
        return "No route optimization data available. The user needs to upload data and compute routes first."
    
    lines = []
    
    # Summary
    summary = results_data.get("summary", {})
    lines.append("=== DELIVERY PLAN SUMMARY ===")
    lines.append(f"Total Active Vehicles: {summary.get('total_fleets', 0)}")
    lines.append(f"Total Parcels Delivered: {summary.get('total_parcels', 0)}")
    lines.append(f"Total Distance: {summary.get('total_distance', 0):.1f} km")
    lines.append(f"Total Cost: ₹{summary.get('total_cost', 0):,.2f}")
    
    warehouse = summary.get("warehouse", {})
    if warehouse:
        lines.append(f"Warehouse Location: ({warehouse.get('lat', 0):.4f}, {warehouse.get('lon', 0):.4f})")
    
    # Per-vehicle details
    lines.append("\n=== VEHICLE DETAILS ===")
    lines.append(f"{'Veh':<5} {'Dist(km)':<10} {'Weight(kg)':<12} {'Cap(kg)':<9} {'Util%':<8} {'Stops':<7} {'Cost(₹)':<10} {'Shift':<15}")
    lines.append("-" * 80)
    
    for v in results_data["vehicles"]:
        vid = v["vehicle_id"]
        lines.append(
            f"V{vid:<4} {v['total_distance']:<10.1f} {v['total_weight']:<12} "
            f"{v['capacity']:<9} {v['utilization']:<8.1f} {v['total_deliveries']:<7} "
            f"₹{v['cost']:<9.0f} {v['clock_in']}-{v['clock_out']}"
        )
    
    # Delivery status breakdown
    lines.append("\n=== DELIVERY STATUS PER VEHICLE ===")
    for v in results_data["vehicles"]:
        statuses = {"ON_TIME": 0, "LATE": 0, "IN_BUFFER": 0, "UNKNOWN": 0}
        for s in v.get("stations", []):
            status = s.get("status", "UNKNOWN")
            statuses[status] = statuses.get(status, 0) + 1
        
        lines.append(f"Vehicle {v['vehicle_id']}: {statuses['ON_TIME']} on-time, {statuses['LATE']} late, {statuses['IN_BUFFER']} in-buffer")
        
        # List stops with arrival times
        for s in v.get("stations", []):
            lines.append(f"  - Parcel {s['station_id']}: arrives {s['arrival_time']}, status: {s['status']}")
    
    # Undelivered parcels
    undelivered = results_data.get("undelivered_parcels", [])
    if undelivered:
        lines.append(f"\n=== UNDELIVERED PARCELS ({len(undelivered)}) ===")
        for p in undelivered:
            lines.append(f"  - Parcel {p['station_id']} at ({p['lat']:.4f}, {p['lon']:.4f})")
    
    # Weather alerts
    weather = results_data.get("weather_alerts", [])
    if weather:
        lines.append(f"\n=== WEATHER ALERTS ({len(weather)}) ===")
        heavy = [w for w in weather if w.get("severity") == "heavy"]
        moderate = [w for w in weather if w.get("severity") == "moderate"]
        clear = [w for w in weather if w.get("severity") not in ("heavy", "moderate")]
        
        if heavy:
            lines.append(f"Heavy rain (10× penalty): {len(heavy)} stations")
            for w in heavy[:5]:
                lines.append(f"  - Station {w['station_id']}: {w['rain_mm']}mm, {w['description']}")
        if moderate:
            lines.append(f"Moderate rain (3× penalty): {len(moderate)} stations")
        if clear:
            lines.append(f"Clear weather: {len(clear)} stations")
    
    # Uploaded data summary
    if uploaded_data_summary:
        lines.append("\n=== UPLOADED DATA INFO ===")
        lines.append(f"Total rows: {uploaded_data_summary.get('row_count', 'N/A')}")
        lines.append(f"Columns: {', '.join(uploaded_data_summary.get('columns', []))}")
        if uploaded_data_summary.get("weight_range"):
            lines.append(f"Weight range: {uploaded_data_summary['weight_range'][0]}-{uploaded_data_summary['weight_range'][1]} kg")
    
    return "\n".join(lines)


async def chat(
    message: str,
    results_data: Dict[str, Any],
    history: List[Dict[str, str]] = None,
    uploaded_data_summary: Optional[Dict] = None
) -> str:
    """
    Send a message to Gemini with VRP data context.
    
    Args:
        message: User's question
        results_data: Current /api/results data
        history: Previous messages [{role: "user"/"model", parts: ["..."]}]
        uploaded_data_summary: Summary of uploaded CSV data
    
    Returns:
        Gemini's response text
    """
    if not GEMINI_API_KEY:
        return "⚠️ Gemini API key not configured. Please add GEMINI_API_KEY to your .env file."
    
    try:
        # Build context from current data
        context = build_data_context(results_data, uploaded_data_summary)
        
        # Create client with API key
        client = genai.Client(api_key=GEMINI_API_KEY)
        
        # Build conversation history for Gemini
        contents = []
        if history:
            for msg in history[-10:]:  # Keep last 10 messages
                contents.append(types.Content(
                    role=msg["role"],
                    parts=[types.Part.from_text(text=msg["content"])]
                ))
        
        # Add current user message
        contents.append(types.Content(
            role="user",
            parts=[types.Part.from_text(text=message)]
        ))
        
        # Send request
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT.format(context=context),
                temperature=0.3,
                max_output_tokens=1024,
            )
        )
        
        return response.text
        
    except Exception as e:
        print(f"❌ Gemini API error: {e}")
        return f"Sorry, I encountered an error: {str(e)}"

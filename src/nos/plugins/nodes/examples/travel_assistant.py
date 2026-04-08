"""
Travel Assistant Node Plugin.

Monitors upcoming flights and travel bookings.
Provides real-time updates on delays and changes.

Module path: nos.plugins.nodes.examples.travel_assistant
Class name:  TravelAssistantNode
Node ID:     travel_assistant

To register this node:
    reg node travel_assistant TravelAssistantNode nos.plugins.nodes.examples.travel_assistant

To execute this node:
    run node db travel_assistant --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime, timedelta
import random


class TravelAssistantNode(Node):
    """
    Travel Assistant - Real-time travel monitoring and alerts.
    
    This node monitors flight schedules, hotel bookings, and travel
    itineraries, providing real-time updates and proactive notifications.
    
    Input params:
        user_id: User identifier for bookings lookup
        check_flights: Monitor flight status (default: True)
        check_hotels: Monitor hotel bookings (default: True)
        alert_window_hours: Hours ahead to check (default: 48)
    
    Output:
        flights: List of upcoming flights with status
        hotels: List of hotel bookings
        alerts: Active travel alerts
        next_trip: Details of next upcoming trip
    """
    
    def __init__(self, node_id: str = "travel_assistant", name: str = None):
        super().__init__(node_id, name or "Travel Assistant")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "Starting travel status check...")
        
        # Get parameters
        check_flights = params_dict.get("check_flights", True)
        check_hotels = params_dict.get("check_hotels", True)
        alert_window = params_dict.get("alert_window_hours", 48)
        
        self.exec_log.log("debug", f"Alert window: {alert_window} hours")
        
        flights = []
        hotels = []
        alerts = []
        
        # Check flights
        if check_flights:
            self.exec_log.log("info", "Checking flight status...")
            
            # Simulate flight data
            now = datetime.now()
            flight_data = [
                {
                    "flight_number": "AZ1284",
                    "route": "MXP → FCO",
                    "airline": "ITA Airways",
                    "scheduled_departure": (now + timedelta(hours=3)).strftime("%H:%M"),
                    "scheduled_arrival": (now + timedelta(hours=4, minutes=30)).strftime("%H:%M"),
                    "status": "delayed",
                    "delay_minutes": 120,
                    "gate": "B12",
                    "terminal": "1"
                },
                {
                    "flight_number": "LH1234",
                    "route": "FCO → FRA",
                    "airline": "Lufthansa",
                    "scheduled_departure": (now + timedelta(days=2, hours=8)).strftime("%Y-%m-%d %H:%M"),
                    "scheduled_arrival": (now + timedelta(days=2, hours=10)).strftime("%Y-%m-%d %H:%M"),
                    "status": "on_time",
                    "delay_minutes": 0,
                    "gate": "TBD",
                    "terminal": "3"
                }
            ]
            
            for flight in flight_data:
                flights.append(flight)
                
                if flight["status"] == "delayed":
                    delay_hours = flight["delay_minutes"] // 60
                    delay_mins = flight["delay_minutes"] % 60
                    
                    alert = {
                        "type": "flight_delay",
                        "severity": "warning" if flight["delay_minutes"] < 60 else "high",
                        "title": f"Flight {flight['flight_number']} Delayed",
                        "message": f"{flight['route']} delayed by {delay_hours}h {delay_mins}m",
                        "flight": flight["flight_number"],
                        "action": "Check updated departure time"
                    }
                    alerts.append(alert)
                    self.exec_log.log("warning", f"⚠️ Flight {flight['flight_number']}: {delay_hours}h {delay_mins}m delay")
                else:
                    self.exec_log.log("debug", f"✓ Flight {flight['flight_number']}: On time")
        
        # Check hotels
        if check_hotels:
            self.exec_log.log("info", "Checking hotel bookings...")
            
            hotel_data = [
                {
                    "hotel": "Grand Hotel Rome",
                    "location": "Rome, Italy",
                    "check_in": (datetime.now() + timedelta(hours=6)).strftime("%Y-%m-%d"),
                    "check_out": (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d"),
                    "room_type": "Superior Double",
                    "confirmation": "GHR-2026-78432",
                    "status": "confirmed"
                },
                {
                    "hotel": "Frankfurt Airport Hilton",
                    "location": "Frankfurt, Germany",
                    "check_in": (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d"),
                    "check_out": (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d"),
                    "room_type": "Executive King",
                    "confirmation": "HLT-2026-99123",
                    "status": "confirmed"
                }
            ]
            
            hotels = hotel_data
            self.exec_log.log("debug", f"Found {len(hotels)} active hotel bookings")
        
        # Determine next trip
        next_trip = None
        if flights:
            next_flight = flights[0]
            next_trip = {
                "flight": next_flight["flight_number"],
                "route": next_flight["route"],
                "departure": next_flight["scheduled_departure"],
                "status": next_flight["status"],
                "gate": next_flight["gate"]
            }
        
        # Summary
        self.exec_log.log("info", "Travel check complete!")
        
        if alerts:
            self.exec_log.log("warning", f"⚠️ {len(alerts)} active alert(s)")
            self.exec_log.log("info", "Has alerts", has_alerts=True)
        else:
            self.exec_log.log("info", "All travel on schedule")
        
        return NodeOutput(
            output={
                "status": "alert" if alerts else "success",
                "flights": flights,
                "hotels": hotels,
                "alerts": alerts,
                "next_trip": next_trip,
                "flights_count": len(flights),
                "hotels_count": len(hotels),
                "alerts_count": len(alerts)
            },
            metadata={
                "executed_by": "TravelAssistantNode",
                "checked_at": datetime.now().isoformat(),
                "alert_window_hours": alert_window
            }
        )

"""
Virtual Secretary Node Plugin.

AI-powered calendar management and appointment scheduling.
Handles meeting requests and calendar coordination.

Module path: nos.plugins.nodes.examples.virtual_secretary
Class name:  VirtualSecretaryNode
Node ID:     virtual_secretary

To register this node:
    reg node virtual_secretary VirtualSecretaryNode nos.plugins.nodes.examples.virtual_secretary

To execute this node:
    run node db virtual_secretary --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime, timedelta
import random


class VirtualSecretaryNode(Node):
    """
    Virtual Secretary - AI-powered calendar and scheduling assistant.
    
    This node manages calendar appointments, processes meeting requests,
    finds optimal meeting times, and handles scheduling conflicts.
    
    Input params:
        action: "status", "schedule", "find_slot", "respond" (default: status)
        calendar_id: Calendar to manage (default: primary)
        meeting_request: Meeting details for scheduling
        duration_minutes: Meeting duration (default: 60)
    
    Output:
        pending_requests: Meeting requests awaiting response
        upcoming_meetings: Next scheduled meetings
        available_slots: Available time slots
        calendar_summary: Daily/weekly summary
    """
    
    def __init__(self, node_id: str = "virtual_secretary", name: str = None):
        super().__init__(node_id, name or "Virtual Secretary")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "👩‍💼 Virtual Secretary starting...")
        
        # Get parameters
        action = params_dict.get("action", "status")
        duration = params_dict.get("duration_minutes", 60)
        
        self.exec_log.log("debug", f"Action: {action}")
        
        now = datetime.now()
        
        # Simulate pending meeting requests
        pending_requests = [
            {
                "id": "req_001",
                "from": "Marco Rossi",
                "email": "m.rossi@company.com",
                "subject": "Q1 Budget Review",
                "proposed_times": [
                    (now + timedelta(days=1, hours=10)).strftime("%Y-%m-%d %H:%M"),
                    (now + timedelta(days=1, hours=14)).strftime("%Y-%m-%d %H:%M"),
                ],
                "duration_minutes": 60,
                "priority": "high",
                "received": (now - timedelta(hours=2)).strftime("%H:%M")
            },
            {
                "id": "req_002",
                "from": "Anna Bianchi",
                "email": "a.bianchi@partner.com",
                "subject": "Partnership Discussion",
                "proposed_times": [
                    (now + timedelta(days=2, hours=11)).strftime("%Y-%m-%d %H:%M"),
                ],
                "duration_minutes": 45,
                "priority": "medium",
                "received": (now - timedelta(hours=5)).strftime("%H:%M")
            },
            {
                "id": "req_003",
                "from": "Tech Team",
                "email": "tech@company.com",
                "subject": "Sprint Planning",
                "proposed_times": [
                    (now + timedelta(days=3, hours=9)).strftime("%Y-%m-%d %H:%M"),
                ],
                "duration_minutes": 90,
                "priority": "normal",
                "received": (now - timedelta(hours=8)).strftime("%H:%M")
            }
        ]
        
        self.exec_log.log("info", f"📬 {len(pending_requests)} pending meeting requests")
        
        # Simulate upcoming meetings
        upcoming_meetings = [
            {
                "title": "Daily Standup",
                "time": (now + timedelta(hours=1)).strftime("%H:%M"),
                "duration": 15,
                "attendees": ["Team"],
                "location": "Zoom"
            },
            {
                "title": "Client Call - Acme Corp",
                "time": (now + timedelta(hours=3)).strftime("%H:%M"),
                "duration": 30,
                "attendees": ["John Smith", "Sales Team"],
                "location": "Teams"
            },
            {
                "title": "Project Review",
                "time": (now + timedelta(days=1, hours=2)).strftime("%Y-%m-%d %H:%M"),
                "duration": 60,
                "attendees": ["PM Team", "Stakeholders"],
                "location": "Conference Room A"
            }
        ]
        
        self.exec_log.log("info", f"📅 {len(upcoming_meetings)} upcoming meetings")
        
        # Find available slots
        self.exec_log.log("info", "Analyzing calendar for available slots...")
        
        available_slots = []
        check_date = now
        
        for day_offset in range(3):
            check_date = now + timedelta(days=day_offset)
            
            # Simulate available slots (business hours 9-18)
            for hour in [10, 11, 14, 15, 16]:
                if random.random() > 0.4:  # 60% chance slot is free
                    slot_time = check_date.replace(hour=hour, minute=0, second=0)
                    if slot_time > now:
                        available_slots.append({
                            "date": slot_time.strftime("%Y-%m-%d"),
                            "time": slot_time.strftime("%H:%M"),
                            "duration_available": random.choice([30, 60, 90])
                        })
        
        # Limit to next 5 slots
        available_slots = sorted(available_slots, key=lambda x: x["date"] + x["time"])[:5]
        
        self.exec_log.log("debug", f"Found {len(available_slots)} available slots")
        
        # Calendar summary
        calendar_summary = {
            "today": {
                "meetings": 3,
                "total_hours": 2.5,
                "free_hours": 5.5
            },
            "tomorrow": {
                "meetings": 4,
                "total_hours": 3.5,
                "free_hours": 4.5
            },
            "week": {
                "meetings": 15,
                "total_hours": 12,
                "busiest_day": "Wednesday"
            }
        }
        
        # Log pending requests
        for req in pending_requests:
            self.exec_log.log("debug", f"📨 From {req['from']}: {req['subject']} ({req['priority']})")
        
        self.exec_log.log("info", "Calendar analysis complete!")
        self.exec_log.log("info", "Pending count updated", pending_count=len(pending_requests))
        
        return NodeOutput(
            output={
                "status": "success",
                "pending_requests": pending_requests,
                "pending_count": len(pending_requests),
                "upcoming_meetings": upcoming_meetings,
                "available_slots": available_slots,
                "next_free_slot": available_slots[0] if available_slots else None,
                "calendar_summary": calendar_summary
            },
            metadata={
                "executed_by": "VirtualSecretaryNode",
                "action": action,
                "timestamp": datetime.now().isoformat()
            }
        )

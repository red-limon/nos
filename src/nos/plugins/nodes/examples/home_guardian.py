"""
Home Guardian Node Plugin.

Smart home security monitoring with AI-powered detection.
Monitors cameras, sensors, and alerts on security events.

Module path: nos.plugins.nodes.examples.home_guardian
Class name:  HomeGuardianNode
Node ID:     home_guardian

To register this node:
    reg node home_guardian HomeGuardianNode nos.plugins.nodes.examples.home_guardian

To execute this node:
    run node db home_guardian --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime, timedelta
import random


class HomeGuardianNode(Node):
    """
    Home Guardian - AI-powered home security monitoring.
    
    This node monitors security cameras, motion sensors, door/window
    sensors, and uses AI to identify persons and potential threats.
    
    Input params:
        mode: Security mode - "away", "home", "night" (default: away)
        cameras: List of cameras to monitor (default: all)
        detect_faces: Enable face recognition (default: True)
        alert_threshold: Motion detection sensitivity (default: medium)
    
    Output:
        status: Current security status
        events: Recent security events
        alerts: Active security alerts
        camera_status: Status of each camera
        sensors_status: Status of sensors
    """
    
    def __init__(self, node_id: str = "home_guardian", name: str = None):
        super().__init__(node_id, name or "Home Guardian")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "🏠 Home Guardian security check starting...")
        
        # Get parameters
        mode = params_dict.get("mode", "away")
        detect_faces = params_dict.get("detect_faces", True)
        sensitivity = params_dict.get("alert_threshold", "medium")
        
        self.exec_log.log("debug", f"Security mode: {mode.upper()}")
        self.exec_log.log("debug", f"Face detection: {'Enabled' if detect_faces else 'Disabled'}")
        
        # Define cameras and sensors
        cameras = [
            {"id": "cam_front", "name": "Front Door", "device": "Ring Doorbell", "location": "entrance"},
            {"id": "cam_back", "name": "Backyard", "device": "Arlo Pro 4", "location": "garden"},
            {"id": "cam_garage", "name": "Garage", "device": "Nest Cam", "location": "garage"},
            {"id": "cam_living", "name": "Living Room", "device": "Wyze Cam", "location": "indoor"}
        ]
        
        sensors = [
            {"id": "door_front", "name": "Front Door", "type": "door", "status": "closed"},
            {"id": "door_back", "name": "Back Door", "type": "door", "status": "closed"},
            {"id": "window_living", "name": "Living Room Window", "type": "window", "status": "closed"},
            {"id": "motion_hallway", "name": "Hallway Motion", "type": "motion", "status": "clear"},
            {"id": "glass_break", "name": "Glass Break Sensor", "type": "glass", "status": "ok"}
        ]
        
        events = []
        alerts = []
        camera_status = []
        
        # Check cameras
        self.exec_log.log("info", "Checking camera feeds...")
        
        for cam in cameras:
            is_online = random.random() > 0.05  # 95% uptime
            has_motion = random.random() > 0.7
            
            cam_info = {
                "id": cam["id"],
                "name": cam["name"],
                "device": cam["device"],
                "online": is_online,
                "motion_detected": has_motion if is_online else False,
                "last_motion": datetime.now().strftime("%H:%M") if has_motion else None
            }
            camera_status.append(cam_info)
            
            if not is_online:
                self.exec_log.log("warning", f"⚠️ Camera offline: {cam['name']}")
                alerts.append({
                    "type": "camera_offline",
                    "severity": "medium",
                    "camera": cam["name"],
                    "message": f"{cam['device']} at {cam['name']} is offline"
                })
            elif has_motion:
                self.exec_log.log("debug", f"🔵 Motion detected: {cam['name']}")
        
        # Simulate security event (for demo)
        if random.random() > 0.6:
            person_detected = {
                "type": "person_detected",
                "camera": "Front Door",
                "time": datetime.now().strftime("%H:%M:%S"),
                "identified": random.choice([True, False]),
                "person_name": "Unknown" if random.random() > 0.5 else "Family Member",
                "confidence": random.uniform(0.75, 0.98)
            }
            events.append(person_detected)
            
            if person_detected["person_name"] == "Unknown":
                self.exec_log.log("error", "🚨 ALERT: Unknown person at front door!")
                alerts.append({
                    "type": "unknown_person",
                    "severity": "critical",
                    "camera": "Front Door",
                    "message": "Motion detected at front door! Person identified: Unknown",
                    "action_required": True,
                    "timestamp": datetime.now().isoformat()
                })
                self.exec_log.log("info", "Alert active", alert_active=True)
            else:
                self.exec_log.log("info", f"✓ Person identified: {person_detected['person_name']}")
        
        # Check sensors
        self.exec_log.log("info", "Checking sensors...")
        
        sensors_ok = True
        for sensor in sensors:
            if random.random() > 0.95:  # 5% chance of issue
                sensor["status"] = "triggered" if sensor["type"] == "motion" else "open"
                sensors_ok = False
                self.exec_log.log("warning", f"⚠️ Sensor alert: {sensor['name']}")
        
        # Overall status
        overall_status = "secure"
        if alerts and any(a["severity"] == "critical" for a in alerts):
            overall_status = "alert"
        elif alerts:
            overall_status = "warning"
        
        self.exec_log.log("info", f"Security check complete. Status: {overall_status.upper()}")
        
        return NodeOutput(
            output={
                "status": overall_status,
                "mode": mode,
                "events": events,
                "alerts": alerts,
                "camera_status": camera_status,
                "sensors": sensors,
                "cameras_online": sum(1 for c in camera_status if c["online"]),
                "cameras_total": len(cameras),
                "sensors_ok": sensors_ok,
                "last_check": datetime.now().isoformat()
            },
            metadata={
                "executed_by": "HomeGuardianNode",
                "security_mode": mode,
                "face_detection": detect_faces
            }
        )

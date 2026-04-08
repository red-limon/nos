"""
Smart Home Node Plugin.

Home automation assistant for appliances and energy management.
Schedules appliances for optimal energy usage.

Module path: nos.plugins.nodes.examples.smart_home
Class name:  SmartHomeNode
Node ID:     smart_home

To register this node:
    reg node smart_home SmartHomeNode nos.plugins.nodes.examples.smart_home

To execute this node:
    run node db smart_home --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime, timedelta
import random


class SmartHomeNode(Node):
    """
    Smart Home - Intelligent home automation and energy management.
    
    This node manages smart home devices, schedules appliances for
    off-peak energy usage, monitors consumption, and automates routines.
    
    Input params:
        action: "status", "schedule", "control", "optimize" (default: status)
        device_id: Specific device to control (optional)
        schedule_time: Time to schedule appliance (for schedule action)
        optimize_for: "cost", "eco", "comfort" (default: cost)
    
    Output:
        devices: Status of all smart devices
        schedules: Active schedules
        energy: Energy consumption data
        recommendations: Energy saving recommendations
    """
    
    def __init__(self, node_id: str = "smart_home", name: str = None):
        super().__init__(node_id, name or "Smart Home")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "🏠 Smart Home assistant starting...")
        
        # Get parameters
        action = params_dict.get("action", "status")
        device_id = params_dict.get("device_id")
        optimize_for = params_dict.get("optimize_for", "cost")
        
        self.exec_log.log("debug", f"Action: {action}")
        self.exec_log.log("debug", f"Optimization: {optimize_for}")
        
        # Define smart devices
        devices = [
            {
                "id": "washer_1",
                "name": "Washing Machine",
                "model": "Samsung WW90",
                "location": "Laundry Room",
                "status": "scheduled",
                "power_watts": 2100,
                "scheduled_for": "22:00"
            },
            {
                "id": "dryer_1",
                "name": "Dryer",
                "model": "Samsung DV90",
                "location": "Laundry Room",
                "status": "idle",
                "power_watts": 2400,
                "scheduled_for": None
            },
            {
                "id": "dishwasher_1",
                "name": "Dishwasher",
                "model": "Bosch Serie 6",
                "location": "Kitchen",
                "status": "running",
                "power_watts": 1800,
                "progress": "65%"
            },
            {
                "id": "hvac_1",
                "name": "HVAC System",
                "model": "Daikin Inverter",
                "location": "Whole House",
                "status": "cooling",
                "power_watts": 3500,
                "target_temp": 22,
                "current_temp": 24
            },
            {
                "id": "ev_charger",
                "name": "EV Charger",
                "model": "Tesla Wall Connector",
                "location": "Garage",
                "status": "scheduled",
                "power_watts": 11000,
                "scheduled_for": "01:00",
                "charge_target": "80%"
            },
            {
                "id": "water_heater",
                "name": "Water Heater",
                "model": "Ariston Smart",
                "location": "Utility Room",
                "status": "standby",
                "power_watts": 2500,
                "water_temp": 55
            }
        ]
        
        self.exec_log.log("info", f"Found {len(devices)} smart devices")
        
        # Get active schedules
        schedules = []
        for device in devices:
            if device.get("scheduled_for"):
                schedules.append({
                    "device": device["name"],
                    "time": device["scheduled_for"],
                    "reason": "Off-peak tariff (cheaper electricity)"
                })
                self.exec_log.log("debug", f"⏰ {device['name']} scheduled for {device['scheduled_for']}")
        
        # Calculate energy stats
        running_devices = [d for d in devices if d["status"] in ["running", "cooling", "heating"]]
        current_power = sum(d["power_watts"] for d in running_devices)
        
        energy = {
            "current_power_watts": current_power,
            "current_power_kw": round(current_power / 1000, 2),
            "today_kwh": round(random.uniform(15, 35), 2),
            "month_kwh": round(random.uniform(400, 600), 2),
            "estimated_cost_today": f"€{random.uniform(3, 8):.2f}",
            "peak_hours": "08:00-20:00",
            "off_peak_hours": "20:00-08:00",
            "current_tariff": "peak" if 8 <= datetime.now().hour < 20 else "off-peak"
        }
        
        self.exec_log.log("info", f"Current power: {energy['current_power_kw']} kW")
        
        # Generate recommendations
        recommendations = []
        
        if energy["current_tariff"] == "peak":
            recommendations.append({
                "type": "schedule",
                "priority": "high",
                "message": "Consider running high-power appliances after 20:00 for cheaper rates",
                "potential_savings": "30-40%"
            })
        
        for device in devices:
            if device["status"] == "idle" and device["power_watts"] > 2000:
                recommendations.append({
                    "type": "optimization",
                    "device": device["name"],
                    "message": f"Schedule {device['name']} for off-peak hours",
                    "potential_savings": "€0.50-1.00 per cycle"
                })
        
        if running_devices:
            self.exec_log.log("debug", f"Active devices: {', '.join(d['name'] for d in running_devices)}")
        
        self.exec_log.log("info", "Smart home status check complete!")
        
        return NodeOutput(
            output={
                "status": "success",
                "devices": devices,
                "devices_running": len(running_devices),
                "devices_scheduled": len(schedules),
                "schedules": schedules,
                "energy": energy,
                "recommendations": recommendations,
                "optimization_mode": optimize_for
            },
            metadata={
                "executed_by": "SmartHomeNode",
                "action": action,
                "timestamp": datetime.now().isoformat()
            }
        )

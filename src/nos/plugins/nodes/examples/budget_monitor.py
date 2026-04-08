"""
Budget Monitor Node Plugin.

Monitors department budgets and spending patterns.
Alerts when spending approaches thresholds.

Module path: nos.plugins.nodes.examples.budget_monitor
Class name:  BudgetMonitorNode
Node ID:     budget_monitor

To register this node:
    reg node budget_monitor BudgetMonitorNode nos.plugins.nodes.examples.budget_monitor

To execute this node:
    run node db budget_monitor --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime
import random


class BudgetMonitorNode(Node):
    """
    Budget Monitor - Real-time budget tracking and alerting.
    
    This node tracks departmental spending against allocated budgets,
    identifies anomalies, forecasts end-of-period spend, and generates alerts.
    
    Input params:
        departments: List of departments to monitor (default: all)
        alert_threshold: Percentage threshold for alerts (default: 80)
        forecast: Generate spend forecast (default: True)
        period: Budget period (default: current month)
    
    Output:
        departments: Budget status per department
        alerts: List of budget alerts
        total_budget: Total allocated budget
        total_spent: Total amount spent
        forecast: Projected end-of-period spending
    """
    
    def __init__(self, node_id: str = "budget_monitor", name: str = None):
        super().__init__(node_id, name or "Budget Monitor")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "Starting budget monitoring...")
        
        # Get parameters
        alert_threshold = params_dict.get("alert_threshold", 80)
        do_forecast = params_dict.get("forecast", True)
        period = params_dict.get("period", datetime.now().strftime("%Y-%m"))
        
        self.exec_log.log("debug", f"Alert threshold: {alert_threshold}%")
        self.exec_log.log("debug", f"Budget period: {period}")
        
        # Define departments with budgets
        departments = {
            "Marketing": {"budget": 30000, "spent": random.randint(20000, 28000)},
            "Engineering": {"budget": 75000, "spent": random.randint(45000, 65000)},
            "Sales": {"budget": 25000, "spent": random.randint(12000, 22000)},
            "Operations": {"budget": 40000, "spent": random.randint(25000, 38000)},
            "HR": {"budget": 15000, "spent": random.randint(8000, 14000)},
            "IT Infrastructure": {"budget": 50000, "spent": random.randint(30000, 48000)},
        }
        
        # Calculate metrics and generate alerts
        alerts = []
        total_budget = 0
        total_spent = 0
        department_status = {}
        
        self.exec_log.log("info", "Analyzing departmental spending...")
        
        for dept, data in departments.items():
            budget = data["budget"]
            spent = data["spent"]
            remaining = budget - spent
            percentage = (spent / budget) * 100
            
            total_budget += budget
            total_spent += spent
            
            status = "ok"
            if percentage >= 90:
                status = "critical"
            elif percentage >= alert_threshold:
                status = "warning"
            
            department_status[dept] = {
                "budget": budget,
                "spent": spent,
                "remaining": remaining,
                "percentage": round(percentage, 1),
                "status": status
            }
            
            self.exec_log.log("debug", f"{dept}: €{spent:,} / €{budget:,} ({percentage:.1f}%)")
            
            # Generate alerts
            if percentage >= alert_threshold:
                alert = {
                    "department": dept,
                    "level": "critical" if percentage >= 90 else "warning",
                    "message": f"{dept} budget at {percentage:.1f}% - €{spent:,} of €{budget:,} spent",
                    "remaining": remaining,
                    "action_required": percentage >= 90
                }
                alerts.append(alert)
                
                if percentage >= 90:
                    self.exec_log.log("error", f"🚨 CRITICAL: {dept} at {percentage:.1f}%!")
                else:
                    self.exec_log.log("warning", f"⚠️ WARNING: {dept} at {percentage:.1f}%")
        
        # Generate forecast
        forecast = None
        if do_forecast:
            self.exec_log.log("info", "Generating end-of-period forecast...")
            
            days_in_month = 30
            day_of_month = datetime.now().day
            daily_rate = total_spent / day_of_month
            projected_total = daily_rate * days_in_month
            
            forecast = {
                "projected_spending": round(projected_total, 2),
                "budget_utilization": round((projected_total / total_budget) * 100, 1),
                "projected_surplus_deficit": round(total_budget - projected_total, 2),
                "confidence": 0.85
            }
            
            self.exec_log.log("info", f"Projected month-end: €{projected_total:,.0f}")
        
        # Summary
        overall_percentage = (total_spent / total_budget) * 100
        self.exec_log.log("info", f"Overall budget utilization: {overall_percentage:.1f}%")
        
        if alerts:
            self.exec_log.log("warning", f"Generated {len(alerts)} budget alerts")
        else:
            self.exec_log.log("info", "All departments within budget")
        
        return NodeOutput(
            output={
                "status": "success" if not any(a["level"] == "critical" for a in alerts) else "alert",
                "departments": department_status,
                "alerts": alerts,
                "total_budget": total_budget,
                "total_spent": total_spent,
                "total_remaining": total_budget - total_spent,
                "overall_percentage": round(overall_percentage, 1),
                "forecast": forecast,
                "period": period
            },
            metadata={
                "executed_by": "BudgetMonitorNode",
                "alert_threshold": alert_threshold,
                "departments_monitored": len(departments)
            }
        )

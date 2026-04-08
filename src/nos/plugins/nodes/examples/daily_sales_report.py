"""
Daily Sales Report Node Plugin.

Generates daily sales summary with KPIs, top products, and regional breakdown.
Sends email to sales team.

Module path: nos.plugins.nodes.examples.daily_sales_report
Class name:  DailySalesReportNode
Node ID:     daily_sales_report

To register this node:
    reg node daily_sales_report DailySalesReportNode nos.plugins.nodes.examples.daily_sales_report

To execute this node:
    run node db daily_sales_report --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime
import random


class DailySalesReportNode(Node):
    """
    Daily Sales Report - Generates comprehensive sales analytics.
    
    This node aggregates sales data from various sources, calculates KPIs,
    identifies top-performing products, and generates regional breakdowns.
    The report can be sent via email to the sales team.
    
    Input params:
        date: Report date (default: today)
        regions: List of regions to include (default: all)
        send_email: Whether to send email notification (default: True)
        recipients: Email recipients list
    
    Output:
        report: Generated report data with KPIs, products, regions
        email_sent: Whether email was successfully sent
    """
    
    def __init__(self, node_id: str = "daily_sales_report", name: str = None):
        super().__init__(node_id, name or "Daily Sales Report")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "Starting Daily Sales Report generation...")
        
        # Get parameters
        report_date = params_dict.get("date", datetime.now().strftime("%Y-%m-%d"))
        regions = params_dict.get("regions", ["North", "South", "East", "West"])
        send_email = params_dict.get("send_email", True)
        
        self.exec_log.log("debug", f"Report date: {report_date}")
        self.exec_log.log("debug", f"Regions: {regions}")
        
        # Simulate data aggregation
        self.exec_log.log("info", "Aggregating sales data from CRM...")
        
        # Generate mock KPIs
        total_sales = random.randint(50000, 150000)
        total_orders = random.randint(200, 500)
        avg_order_value = total_sales / total_orders
        conversion_rate = random.uniform(2.5, 5.0)
        
        kpis = {
            "total_sales": total_sales,
            "total_orders": total_orders,
            "avg_order_value": round(avg_order_value, 2),
            "conversion_rate": round(conversion_rate, 2),
            "compared_to_yesterday": f"+{random.randint(1, 15)}%"
        }
        
        self.exec_log.log("info", f"Total Sales: €{total_sales:,}")
        self.exec_log.log("info", "KPIs calculated", kpis=kpis)
        
        # Generate top products
        self.exec_log.log("info", "Analyzing top products...")
        top_products = [
            {"name": "Product A Premium", "sales": random.randint(5000, 15000), "units": random.randint(50, 150)},
            {"name": "Product B Standard", "sales": random.randint(3000, 10000), "units": random.randint(80, 200)},
            {"name": "Product C Basic", "sales": random.randint(2000, 8000), "units": random.randint(100, 300)},
        ]
        
        # Generate regional breakdown
        self.exec_log.log("info", "Calculating regional breakdown...")
        regional_data = {}
        for region in regions:
            regional_data[region] = {
                "sales": random.randint(10000, 40000),
                "orders": random.randint(40, 150),
                "growth": f"+{random.randint(-5, 20)}%"
            }
        
        # Compile report
        report = {
            "date": report_date,
            "generated_at": datetime.now().isoformat(),
            "kpis": kpis,
            "top_products": top_products,
            "regional_breakdown": regional_data,
            "summary": f"Strong performance with €{total_sales:,} in total sales across {len(regions)} regions."
        }
        
        # Simulate email sending
        email_sent = False
        if send_email:
            self.exec_log.log("info", "Sending report to sales team...")
            email_sent = True
            self.exec_log.log("info", "Email sent successfully!")
        
        self.exec_log.log("info", "Daily Sales Report generation completed!")
        
        return NodeOutput(
            output={
                "status": "success",
                "report": report,
                "email_sent": email_sent
            },
            metadata={
                "executed_by": "DailySalesReportNode",
                "report_date": report_date,
                "regions_count": len(regions)
            }
        )

"""
Invoice Generator Node Plugin.

Generates and sends monthly invoices to all active clients.
Integrates with accounting system.

Module path: nos.plugins.nodes.examples.invoice_generator
Class name:  InvoiceGeneratorNode
Node ID:     invoice_generator

To register this node:
    reg node invoice_generator InvoiceGeneratorNode nos.plugins.nodes.examples.invoice_generator

To execute this node:
    run node db invoice_generator --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime
import random


class InvoiceGeneratorNode(Node):
    """
    Invoice Generator - Creates and sends professional invoices.
    
    This node retrieves billing data, generates PDF invoices,
    sends them to clients, and updates the accounting system.
    
    Input params:
        period: Billing period (default: current month)
        clients: List of client IDs (default: all active)
        send_email: Send invoices via email (default: True)
        format: Invoice format - "pdf" or "html" (default: pdf)
    
    Output:
        invoices_generated: Number of invoices created
        total_amount: Total billing amount
        emails_sent: Number of emails sent
        failed: List of failed invoice generations
    """
    
    def __init__(self, node_id: str = "invoice_generator", name: str = None):
        super().__init__(node_id, name or "Invoice Generator")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "Starting invoice generation process...")
        
        # Get parameters
        period = params_dict.get("period", datetime.now().strftime("%Y-%m"))
        send_email = params_dict.get("send_email", True)
        invoice_format = params_dict.get("format", "pdf")
        
        self.exec_log.log("debug", f"Billing period: {period}")
        self.exec_log.log("debug", f"Format: {invoice_format.upper()}")
        
        # Simulate fetching active clients
        self.exec_log.log("info", "Fetching active clients from CRM...")
        
        clients = [
            {"id": "CLI001", "name": "Acme Corporation", "email": "billing@acme.com"},
            {"id": "CLI002", "name": "TechStart Inc.", "email": "accounts@techstart.io"},
            {"id": "CLI003", "name": "Global Services Ltd", "email": "finance@globalserv.com"},
            {"id": "CLI004", "name": "Innovation Labs", "email": "billing@innolabs.eu"},
            {"id": "CLI005", "name": "Premier Solutions", "email": "ap@premier.com"},
        ]
        
        self.exec_log.log("info", f"Found {len(clients)} active clients")
        
        # Generate invoices
        invoices = []
        total_amount = 0
        emails_sent = 0
        failed = []
        
        for client in clients:
            self.exec_log.log("info", f"Generating invoice for {client['name']}...")
            
            # Calculate mock invoice amount
            amount = random.randint(1000, 15000)
            invoice_number = f"INV-{period.replace('-', '')}-{client['id']}"
            
            invoice = {
                "number": invoice_number,
                "client_id": client["id"],
                "client_name": client["name"],
                "amount": amount,
                "currency": "EUR",
                "due_date": f"{period}-28",
                "items": [
                    {"description": "Monthly Service Fee", "amount": int(amount * 0.7)},
                    {"description": "Support Package", "amount": int(amount * 0.2)},
                    {"description": "Additional Services", "amount": int(amount * 0.1)},
                ]
            }
            
            invoices.append(invoice)
            total_amount += amount
            
            self.exec_log.log("debug", f"Invoice {invoice_number}: €{amount:,}")
            
            # Simulate email sending
            if send_email:
                if random.random() > 0.1:  # 90% success rate
                    emails_sent += 1
                    self.exec_log.log("debug", f"Email sent to {client['email']}")
                else:
                    failed.append({"client": client["name"], "reason": "Email delivery failed"})
                    self.exec_log.log("warning", f"Failed to send email to {client['email']}")
        
        # Update accounting system
        self.exec_log.log("info", "Updating accounting system...")
        self.exec_log.log("info", "Accounting system synced", accounting_synced=True)
        
        self.exec_log.log("info", "Invoice generation completed!")
        self.exec_log.log("info", f"Total: {len(invoices)} invoices, €{total_amount:,}")
        
        return NodeOutput(
            output={
                "status": "success",
                "invoices_generated": len(invoices),
                "total_amount": total_amount,
                "currency": "EUR",
                "emails_sent": emails_sent,
                "failed": failed,
                "period": period,
                "invoices": invoices
            },
            metadata={
                "executed_by": "InvoiceGeneratorNode",
                "period": period,
                "format": invoice_format
            }
        )

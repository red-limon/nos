"""
Account Payable Node Plugin.

Automated supplier invoice approval workflow.
Processes invoices and routes for approval.

Module path: nos.plugins.nodes.examples.account_payable
Class name:  AccountPayableNode
Node ID:     account_payable

To register this node:
    reg node account_payable AccountPayableNode nos.plugins.nodes.examples.account_payable

To execute this node:
    run node db account_payable --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime
import random


class AccountPayableNode(Node):
    """
    Account Payable - Intelligent invoice processing and approval.
    
    This node processes incoming supplier invoices, validates against
    purchase orders, applies approval rules, and routes exceptions
    for manual review.
    
    Input params:
        auto_approve_limit: Max amount for auto-approval (default: 5000)
        validate_po: Validate against purchase orders (default: True)
        notify_approvers: Send notifications (default: True)
    
    Output:
        invoices_processed: Total invoices processed
        auto_approved: Invoices auto-approved
        pending_review: Invoices requiring manual review
        rejected: Invoices rejected
        total_amount: Total invoice amount
    """
    
    def __init__(self, node_id: str = "account_payable", name: str = None):
        super().__init__(node_id, name or "Account Payable")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "Starting invoice processing...")
        
        # Get parameters
        auto_approve_limit = params_dict.get("auto_approve_limit", 5000)
        validate_po = params_dict.get("validate_po", True)
        notify_approvers = params_dict.get("notify_approvers", True)
        
        self.exec_log.log("debug", f"Auto-approve limit: €{auto_approve_limit:,}")
        
        # Simulate incoming invoices
        suppliers = [
            "Office Supplies Inc", "Tech Hardware Ltd", "Cloud Services Corp",
            "Marketing Agency", "Consulting Partners", "Logistics Express",
            "Software Licenses SA", "Maintenance Services"
        ]
        
        num_invoices = random.randint(10, 20)
        self.exec_log.log("info", f"Processing {num_invoices} incoming invoices...")
        
        auto_approved = []
        pending_review = []
        rejected = []
        total_amount = 0
        
        for i in range(num_invoices):
            supplier = random.choice(suppliers)
            amount = random.randint(500, 12000)
            has_po = random.random() > 0.15  # 85% have valid PO
            po_match = random.random() > 0.1 if has_po else False
            
            invoice = {
                "id": f"INV-{datetime.now().strftime('%Y%m%d')}-{i+1:04d}",
                "supplier": supplier,
                "amount": amount,
                "currency": "EUR",
                "has_po": has_po,
                "po_match": po_match,
                "date": datetime.now().strftime("%Y-%m-%d")
            }
            
            total_amount += amount
            
            # Apply approval rules
            if validate_po and not has_po:
                invoice["status"] = "rejected"
                invoice["reason"] = "No purchase order found"
                rejected.append(invoice)
                self.exec_log.log("warning", f"❌ {invoice['id']}: Rejected - No PO")
            elif validate_po and not po_match:
                invoice["status"] = "pending"
                invoice["reason"] = "PO amount mismatch"
                pending_review.append(invoice)
                self.exec_log.log("debug", f"⏳ {invoice['id']}: Pending review - PO mismatch")
            elif amount > auto_approve_limit:
                invoice["status"] = "pending"
                invoice["reason"] = f"Amount exceeds auto-approve limit (€{auto_approve_limit:,})"
                pending_review.append(invoice)
                self.exec_log.log("debug", f"⏳ {invoice['id']}: Pending review - Over limit")
            else:
                invoice["status"] = "approved"
                auto_approved.append(invoice)
                self.exec_log.log("debug", f"✓ {invoice['id']}: Auto-approved (€{amount:,})")
        
        # Summary
        self.exec_log.log("info", "Processing complete!")
        self.exec_log.log("info", f"✓ Auto-approved: {len(auto_approved)}")
        
        if pending_review:
            self.exec_log.log("warning", f"⏳ Pending review: {len(pending_review)}")
        
        if rejected:
            self.exec_log.log("error", f"❌ Rejected: {len(rejected)}")
        
        # Notify approvers
        if notify_approvers and pending_review:
            self.exec_log.log("info", "Sending notifications to approvers...")
            self.exec_log.log("info", "Notifications sent", notifications_sent=True)
        
        return NodeOutput(
            output={
                "status": "success",
                "invoices_processed": num_invoices,
                "auto_approved": len(auto_approved),
                "auto_approved_amount": sum(inv["amount"] for inv in auto_approved),
                "pending_review": len(pending_review),
                "pending_invoices": pending_review,
                "rejected": len(rejected),
                "rejected_invoices": rejected,
                "total_amount": total_amount,
                "currency": "EUR"
            },
            metadata={
                "executed_by": "AccountPayableNode",
                "auto_approve_limit": auto_approve_limit,
                "validate_po": validate_po
            }
        )

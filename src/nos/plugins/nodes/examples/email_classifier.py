"""
Email Classifier Node Plugin.

AI-powered email classification and routing.
Analyzes incoming emails and assigns to appropriate teams.

Module path: nos.plugins.nodes.examples.email_classifier
Class name:  EmailClassifierNode
Node ID:     email_classifier

To register this node:
    reg node email_classifier EmailClassifierNode nos.plugins.nodes.examples.email_classifier

To execute this node:
    run node db email_classifier --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime
import random


class EmailClassifierNode(Node):
    """
    Email Classifier - AI-powered email triage and routing.
    
    This node fetches unprocessed emails, analyzes content using NLP,
    classifies them by category and urgency, and routes to appropriate teams.
    
    Input params:
        mailbox: Email mailbox to process (default: "inbox")
        max_emails: Maximum emails to process (default: 50)
        auto_reply: Send auto-reply for certain categories (default: True)
        model: AI model for classification (default: "gpt-4")
    
    Output:
        processed: Number of emails processed
        classifications: Breakdown by category
        routed: Number of emails routed to teams
        auto_replies: Number of auto-replies sent
    """
    
    def __init__(self, node_id: str = "email_classifier", name: str = None):
        super().__init__(node_id, name or "Email Classifier")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "Starting email classification process...")
        
        # Get parameters
        mailbox = params_dict.get("mailbox", "inbox")
        max_emails = params_dict.get("max_emails", 50)
        auto_reply = params_dict.get("auto_reply", True)
        model = params_dict.get("model", "gpt-4")
        
        self.exec_log.log("debug", f"Processing mailbox: {mailbox}")
        self.exec_log.log("debug", f"AI Model: {model}")
        
        # Define categories and teams
        categories = {
            "sales_inquiry": {"team": "Sales", "urgency": "high", "auto_reply": True},
            "support_request": {"team": "Support", "urgency": "medium", "auto_reply": True},
            "billing_question": {"team": "Finance", "urgency": "medium", "auto_reply": False},
            "partnership": {"team": "Business Dev", "urgency": "low", "auto_reply": False},
            "complaint": {"team": "Customer Success", "urgency": "high", "auto_reply": True},
            "spam": {"team": None, "urgency": "none", "auto_reply": False},
            "general": {"team": "General", "urgency": "low", "auto_reply": False},
        }
        
        # Simulate fetching emails
        self.exec_log.log("info", f"Fetching unprocessed emails (max: {max_emails})...")
        
        num_emails = random.randint(10, max_emails)
        self.exec_log.log("info", f"Found {num_emails} emails to process")
        
        # Process emails
        classifications = {cat: 0 for cat in categories}
        routed_count = 0
        auto_reply_count = 0
        processed_emails = []
        
        for i in range(num_emails):
            # Simulate AI classification
            category = random.choice(list(categories.keys()))
            confidence = random.uniform(0.75, 0.99)
            
            email_data = {
                "id": f"email_{i+1:04d}",
                "subject": f"Sample email {i+1}",
                "category": category,
                "confidence": round(confidence, 2),
                "team": categories[category]["team"],
                "urgency": categories[category]["urgency"]
            }
            
            classifications[category] += 1
            
            # Route to team
            if categories[category]["team"]:
                routed_count += 1
                self.exec_log.log("debug", f"Email {i+1}: {category} → {categories[category]['team']}")
            
            # Send auto-reply if applicable
            if auto_reply and categories[category]["auto_reply"]:
                auto_reply_count += 1
            
            processed_emails.append(email_data)
            
            # Log progress every 10 emails
            if (i + 1) % 10 == 0:
                self.exec_log.log("info", f"Processed {i+1}/{num_emails} emails...")
        
        # Filter out zero counts
        classifications = {k: v for k, v in classifications.items() if v > 0}
        
        self.exec_log.log("info", "Email classification completed!")
        self.exec_log.log("info", f"Processed: {num_emails}, Routed: {routed_count}, Auto-replies: {auto_reply_count}")
        
        # Emit summary
        self.exec_log.log("info", "Email stats ready", email_stats={
            "processed": num_emails,
            "routed": routed_count,
            "spam_filtered": classifications.get("spam", 0)
        })
        
        return NodeOutput(
            output={
                "status": "success",
                "processed": num_emails,
                "classifications": classifications,
                "routed": routed_count,
                "auto_replies": auto_reply_count,
                "spam_filtered": classifications.get("spam", 0),
                "high_urgency": sum(1 for e in processed_emails if e["urgency"] == "high")
            },
            metadata={
                "executed_by": "EmailClassifierNode",
                "model": model,
                "mailbox": mailbox
            }
        )

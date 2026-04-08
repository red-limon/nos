"""
Quality Expert Node Plugin.

AI knowledge assistant specialized in ISO 9001, quality management systems,
audits, and continuous improvement.

Module path: nos.plugins.nodes.examples.quality_expert
Class name:  QualityExpertNode
Node ID:     quality_expert

To register this node:
    reg node quality_expert QualityExpertNode nos.plugins.nodes.examples.quality_expert

To execute this node:
    run node db quality_expert --sync --debug
"""

from nos.core.engine.base import Node, NodeOutput
from datetime import datetime


class QualityExpertNode(Node):
    """
    Quality Expert - AI-powered quality management assistant.
    
    This node provides expert knowledge on quality management systems,
    ISO standards, audit preparation, and continuous improvement methodologies.
    
    Input params:
        query: User question about quality management
        context: Additional context (default: "general")
        include_references: Include standard references (default: True)
        language: Response language (default: "en")
    
    Output:
        answer: Expert response to the query
        references: Relevant ISO/standard references
        related_topics: Related topics for further exploration
        confidence: Confidence score for the response
    """
    
    def __init__(self, node_id: str = "quality_expert", name: str = None):
        super().__init__(node_id, name or "Quality Expert")
    
    def _do_execute(self, state_dict: dict, params_dict: dict) -> NodeOutput:
        self.exec_log.log("info", "Quality Expert assistant activated...")
        
        # Get parameters
        query = params_dict.get("query", "What are the key principles of ISO 9001?")
        context = params_dict.get("context", "general")
        include_references = params_dict.get("include_references", True)
        
        self.exec_log.log("info", f"Query: {query}")
        self.exec_log.log("debug", f"Context: {context}")
        
        # Knowledge base (simplified for demo)
        knowledge_base = {
            "iso9001_principles": {
                "answer": """ISO 9001 is based on seven quality management principles:

1. **Customer Focus** - Understanding and meeting customer requirements
2. **Leadership** - Establishing unity of purpose and direction
3. **Engagement of People** - Competent, empowered, and engaged personnel
4. **Process Approach** - Managing activities as interrelated processes
5. **Improvement** - Ongoing focus on improvement
6. **Evidence-based Decision Making** - Decisions based on data analysis
7. **Relationship Management** - Managing relationships with interested parties

These principles form the foundation of any effective Quality Management System (QMS).""",
                "references": ["ISO 9001:2015 Section 0.2", "ISO 9000:2015 Quality management principles"],
                "related": ["PDCA cycle", "Risk-based thinking", "Process mapping"]
            },
            "pdca": {
                "answer": """The PDCA (Plan-Do-Check-Act) cycle, also known as the Deming Cycle, is a continuous improvement methodology:

**PLAN** - Identify objectives, processes, and resources needed
**DO** - Implement the plan and collect data
**CHECK** - Monitor and measure results against objectives
**ACT** - Take actions to improve performance

PDCA is fundamental to ISO 9001 and drives continuous improvement in quality management systems.""",
                "references": ["ISO 9001:2015 Section 0.3.2", "Deming, W.E. Out of the Crisis"],
                "related": ["Continuous improvement", "Root cause analysis", "Corrective actions"]
            },
            "audit": {
                "answer": """Internal audits are a key requirement of ISO 9001:2015. Key points:

**Purpose**: Verify QMS conformity and effectiveness
**Frequency**: Planned intervals based on importance and previous results
**Auditor Requirements**: Objective and impartial
**Documentation**: Audit program, criteria, scope, methods, reports

**Best Practices**:
- Use a risk-based approach to prioritize areas
- Prepare audit checklists aligned with ISO requirements
- Focus on evidence and objective findings
- Follow up on corrective actions from previous audits""",
                "references": ["ISO 9001:2015 Section 9.2", "ISO 19011:2018 Guidelines for auditing"],
                "related": ["Management review", "Nonconformity", "Corrective action"]
            }
        }
        
        # Determine response based on query keywords
        query_lower = query.lower()
        response_key = "iso9001_principles"  # default
        
        if "pdca" in query_lower or "plan do check" in query_lower or "deming" in query_lower:
            response_key = "pdca"
        elif "audit" in query_lower or "internal audit" in query_lower:
            response_key = "audit"
        
        knowledge = knowledge_base[response_key]
        
        self.exec_log.log("info", "Analyzing query and retrieving knowledge...")
        
        # Build response
        answer = knowledge["answer"]
        references = knowledge["references"] if include_references else []
        related = knowledge["related"]
        
        self.exec_log.log("info", "Response generated")
        
        # Emit conversation state
        self.exec_log.log("info", "Conversation updated", conversation={
            "query": query,
            "answered": True,
            "topic": response_key
        })
        
        return NodeOutput(
            output={
                "status": "success",
                "answer": answer,
                "references": references,
                "related_topics": related,
                "confidence": 0.92,
                "source": "Quality Management Knowledge Base",
                "can_follow_up": True
            },
            metadata={
                "executed_by": "QualityExpertNode",
                "query": query,
                "topic_detected": response_key,
                "timestamp": datetime.now().isoformat()
            }
        )

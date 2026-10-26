"""Graph ontology shared by every instance. Typed nodes and edges; JSON export for the viewer."""
from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(StrEnum):
    ORGANIZATION = "Organization"
    ORG_UNIT = "OrgUnit"
    PERSON = "Person"            # individual employee or employee archetype
    ROLE = "Role"                # bound to an O*NET-SOC occupation
    OCCUPATION = "Occupation"    # O*NET-SOC code
    GWA = "GWA"                  # generalized work activity
    IWA = "IWA"                  # intermediate work activity
    DWA = "DWA"                  # detailed work activity
    TASK = "Task"                # O*NET occupation-specific task
    ACTIVITY = "Activity"        # instance activity (e.g. an event-log activity type)
    WORK_ITEM = "WorkItem"       # case, ticket, PO line, request
    ARTIFACT = "Artifact"
    SYSTEM = "System"            # tool or software
    CAPABILITY = "Capability"    # what a system can do (MCP-style)
    LOCATION = "Location"
    EXTERNAL_ACTOR = "ExternalActor"  # vendor, client, customer
    MESSAGE = "Message"
    POLICY = "Policy"            # intervention / scenario lever
    EVENT = "Event"
    STATE = "LatentState"        # belief, sentiment, workload attached to a Person


class EdgeType(StrEnum):
    HAS = "has"                  # Organization -> OrgUnit, OrgUnit -> OrgUnit (contains; inverse of part_of)
    MEMBER_OF = "member_of"
    REPORTS_TO = "reports_to"
    SHARES_OFFICE = "shares_office"
    FRIEND_OF = "friend_of"
    SAME_MANAGER = "same_manager"
    HAS_ROLE = "has_role"
    BOUND_TO = "bound_to"        # Role -> Occupation
    PERFORMS = "performs"        # Role/Occupation -> Activity/Task
    PART_OF = "part_of"          # DWA -> IWA -> GWA ; Task -> Occupation
    MAPS_TO = "maps_to"          # Activity -> DWA / Task
    ASSIGNED_TO = "assigned_to"  # WorkItem -> Person/OrgUnit
    PRODUCES = "produces"        # Activity -> Artifact
    USES = "uses"                # Activity/Role -> Capability/System
    PROVIDES = "provides"        # System -> Capability
    DEPENDS_ON = "depends_on"    # WorkItem -> WorkItem, Activity -> Activity
    PRECEDES = "precedes"        # Activity -> Activity (process order), Event -> Event
    SENT_TO = "sent_to"
    AFFECTS = "affects"          # Policy -> any
    HAS_STATE = "has_state"      # Person -> LatentState
    INTERACTS_WITH = "interacts_with"  # ExternalActor -> OrgUnit/Activity
    LOCATED_AT = "located_at"    # Person/OrgUnit -> Location (office, home, site)
    PERFORMED_BY = "performed_by"  # Event -> Person
    CONCERNS = "concerns"        # Event -> WorkItem / Activity
    SENT_BY = "sent_by"          # Message -> Person
    HANDS_OFF_TO = "hands_off_to"  # Person -> Person: a work item passed from one to the other (consecutive events in a case)


CONCEPTS: dict[NodeType, str] = {
    NodeType.ORGANIZATION: "The company or group being simulated. Root of the org-unit tree.",
    NodeType.ORG_UNIT: "A division, department or team. Units nest (part_of) and hold people and roles.",
    NodeType.PERSON: "An employee, played as a digital twin: real covariates, a fixed trait layer, weekly latent states and a seat whose policy makes its decisions. Archetypes when the data has no individuals.",
    NodeType.ROLE: "A job in this organisation (e.g. purchasing clerk, software engineer). Bound to one O*NET-SOC occupation; performs the instance's activities.",
    NodeType.OCCUPATION: "An O*NET-SOC 31.0 occupation, the shared vocabulary that lets roles in different companies be compared.",
    NodeType.GWA: "O*NET generalized work activity: the top level of the activity hierarchy (41 items).",
    NodeType.IWA: "O*NET intermediate work activity (332 items), between GWAs and DWAs.",
    NodeType.DWA: "O*NET detailed work activity (2,087 items). Every instance activity maps to at least one DWA.",
    NodeType.TASK: "An O*NET occupation-specific task statement.",
    NodeType.ACTIVITY: "Something a role does in this organisation on the simulated clock (an event-log step, a customer call, a code review). Carries a weight and a remote-feasibility flag.",
    NodeType.WORK_ITEM: "The unit of work that flows through activities: a purchase-order line, a case, a ticket.",
    NodeType.ARTIFACT: "A document or output an activity produces (invoice, merged code change, review).",
    NodeType.SYSTEM: "A tool or software system (ERP, CRM, code repository) that exposes capabilities.",
    NodeType.CAPABILITY: "One thing a system can do, in the MCP sense; activities use capabilities. Automating a capability is a policy lever.",
    NodeType.LOCATION: "A place work happens: an office, a home, a plant. Hybrid-work policies move people between locations.",
    NodeType.EXTERNAL_ACTOR: "A vendor, client or customer outside the organisation that interacts with its activities.",
    NodeType.MESSAGE: "A communication between people (email, chat, meeting invitation).",
    NodeType.POLICY: "An intervention or scenario lever: a work-from-home offer, an automation, a hiring wave. Affects roles, activities, capabilities, units or locations.",
    NodeType.EVENT: "One recorded occurrence on the clock: a person performed an activity on a work item at a time. The trace is a sequence of events.",
    NodeType.STATE: "A latent, time-varying quantity attached to a person: job satisfaction, work-life balance, attachment, commute burden. Updated weekly by the kernel.",
}

RELATIONS: dict[EdgeType, str] = {
    EdgeType.HAS: "Contains: an organisation has its units, a unit has its sub-units (the inverse reading of part_of).",
    EdgeType.MEMBER_OF: "Belongs to an organisational unit (person or role in a team or division).",
    EdgeType.REPORTS_TO: "Line-management relationship between two people.",
    EdgeType.SHARES_OFFICE: "Two people sit in the same office space; a channel for contagion and comparison.",
    EdgeType.FRIEND_OF: "Informal tie between two people.",
    EdgeType.SAME_MANAGER: "Two people report to the same manager (teammates). Sentiment and comparison spread along this edge.",
    EdgeType.HAS_ROLE: "A person holds a role.",
    EdgeType.BOUND_TO: "A role is bound to an O*NET-SOC occupation.",
    EdgeType.PERFORMS: "A role performs an activity; an occupation performs an O*NET task.",
    EdgeType.PART_OF: "Containment: unit in organisation, DWA in IWA in GWA.",
    EdgeType.MAPS_TO: "An activity or task is expressed as an O*NET detailed work activity.",
    EdgeType.ASSIGNED_TO: "A work item is currently with a person or unit.",
    EdgeType.PRODUCES: "An activity produces an artifact.",
    EdgeType.USES: "An activity or role uses a system capability.",
    EdgeType.PROVIDES: "A system provides a capability.",
    EdgeType.DEPENDS_ON: "A work item or activity cannot proceed before another one.",
    EdgeType.PRECEDES: "Process order: this activity (or event) comes before that one.",
    EdgeType.SENT_TO: "A message is addressed to a person.",
    EdgeType.AFFECTS: "A policy changes the target: who may work where, how long a step takes, how many people hold a role.",
    EdgeType.HAS_STATE: "A person carries a latent state.",
    EdgeType.INTERACTS_WITH: "An external actor takes part in an activity or deals with a unit.",
    EdgeType.LOCATED_AT: "A person or unit works at a location (office, home, site).",
    EdgeType.PERFORMED_BY: "An event was carried out by a person.",
    EdgeType.CONCERNS: "An event is an instance of an activity, applied to a work item.",
    EdgeType.SENT_BY: "A message was sent by a person.",
    EdgeType.HANDS_OFF_TO: "Work passed from one person to another: consecutive events on the same work item by different people. Weighted by how often.",
}


class Node(BaseModel):
    id: str
    type: NodeType
    label: str
    properties: dict[str, Any] = Field(default_factory=dict)


class Edge(BaseModel):
    source: str
    target: str
    type: EdgeType
    properties: dict[str, Any] = Field(default_factory=dict)


class Graph(BaseModel):
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)

    def add_node(self, node: Node) -> Node:
        if not any(n.id == node.id for n in self.nodes):
            self.nodes.append(node)
        return node

    def add_edge(self, edge: Edge) -> Edge:
        self.edges.append(edge)
        return edge

    def merge(self, other: "Graph") -> "Graph":
        ids = {n.id for n in self.nodes}
        for n in other.nodes:
            if n.id not in ids:
                self.nodes.append(n)
                ids.add(n.id)
        seen = {(e.source, e.target, e.type) for e in self.edges}
        for e in other.edges:
            key = (e.source, e.target, e.type)
            if key not in seen:
                self.edges.append(e)
                seen.add(key)
        return self

    def to_json(self) -> dict[str, Any]:
        return {
            "nodes": [n.model_dump(mode="json") for n in self.nodes],
            "edges": [e.model_dump(mode="json") for e in self.edges],
            "stats": self.stats(),
        }

    def stats(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for n in self.nodes:
            by_type[str(n.type)] = by_type.get(str(n.type), 0) + 1
        edges_by_type: dict[str, int] = {}
        for e in self.edges:
            edges_by_type[str(e.type)] = edges_by_type.get(str(e.type), 0) + 1
        return {"nodes": len(self.nodes), "edges": len(self.edges), "nodes_by_type": by_type, "edges_by_type": edges_by_type}


def schema_graph() -> Graph:
    """The ontology schema itself as a graph (node types and allowed edge types), for the viewer."""
    g = Graph()
    for t in NodeType:
        g.add_node(Node(id=f"type:{t}", type=t, label=str(t), properties={"schema": True, "description": CONCEPTS.get(t, "")}))
    allowed = [
        (NodeType.ORGANIZATION, EdgeType.HAS, NodeType.ORG_UNIT),
        (NodeType.ORG_UNIT, EdgeType.HAS, NodeType.ORG_UNIT),
        (NodeType.PERSON, EdgeType.MEMBER_OF, NodeType.ORG_UNIT),
        (NodeType.ORG_UNIT, EdgeType.PART_OF, NodeType.ORGANIZATION),
        (NodeType.PERSON, EdgeType.REPORTS_TO, NodeType.PERSON),
        (NodeType.PERSON, EdgeType.SHARES_OFFICE, NodeType.PERSON),
        (NodeType.PERSON, EdgeType.FRIEND_OF, NodeType.PERSON),
        (NodeType.PERSON, EdgeType.HAS_ROLE, NodeType.ROLE),
        (NodeType.ROLE, EdgeType.BOUND_TO, NodeType.OCCUPATION),
        (NodeType.ROLE, EdgeType.PERFORMS, NodeType.ACTIVITY),
        (NodeType.OCCUPATION, EdgeType.PERFORMS, NodeType.TASK),
        (NodeType.TASK, EdgeType.MAPS_TO, NodeType.DWA),
        (NodeType.ACTIVITY, EdgeType.MAPS_TO, NodeType.DWA),
        (NodeType.DWA, EdgeType.PART_OF, NodeType.IWA),
        (NodeType.IWA, EdgeType.PART_OF, NodeType.GWA),
        (NodeType.WORK_ITEM, EdgeType.ASSIGNED_TO, NodeType.PERSON),
        (NodeType.ACTIVITY, EdgeType.PRODUCES, NodeType.ARTIFACT),
        (NodeType.ACTIVITY, EdgeType.USES, NodeType.CAPABILITY),
        (NodeType.SYSTEM, EdgeType.PROVIDES, NodeType.CAPABILITY),
        (NodeType.ACTIVITY, EdgeType.PRECEDES, NodeType.ACTIVITY),
        (NodeType.WORK_ITEM, EdgeType.DEPENDS_ON, NodeType.WORK_ITEM),
        (NodeType.EXTERNAL_ACTOR, EdgeType.INTERACTS_WITH, NodeType.ACTIVITY),
        (NodeType.MESSAGE, EdgeType.SENT_TO, NodeType.PERSON),
        (NodeType.MESSAGE, EdgeType.SENT_BY, NodeType.PERSON),
        (NodeType.POLICY, EdgeType.AFFECTS, NodeType.ROLE),
        (NodeType.POLICY, EdgeType.AFFECTS, NodeType.ACTIVITY),
        (NodeType.POLICY, EdgeType.AFFECTS, NodeType.CAPABILITY),
        (NodeType.POLICY, EdgeType.AFFECTS, NodeType.ORG_UNIT),
        (NodeType.POLICY, EdgeType.AFFECTS, NodeType.LOCATION),
        (NodeType.PERSON, EdgeType.HAS_STATE, NodeType.STATE),
        (NodeType.PERSON, EdgeType.LOCATED_AT, NodeType.LOCATION),
        (NodeType.PERSON, EdgeType.HANDS_OFF_TO, NodeType.PERSON),
        (NodeType.ORG_UNIT, EdgeType.LOCATED_AT, NodeType.LOCATION),
        (NodeType.EVENT, EdgeType.PERFORMED_BY, NodeType.PERSON),
        (NodeType.EVENT, EdgeType.CONCERNS, NodeType.ACTIVITY),
        (NodeType.EVENT, EdgeType.CONCERNS, NodeType.WORK_ITEM),
        (NodeType.EVENT, EdgeType.PRECEDES, NodeType.EVENT),
        (NodeType.WORK_ITEM, EdgeType.ASSIGNED_TO, NodeType.ORG_UNIT),
        (NodeType.EXTERNAL_ACTOR, EdgeType.INTERACTS_WITH, NodeType.ORG_UNIT),
    ]
    for s, e, t in allowed:
        g.add_edge(Edge(source=f"type:{s}", target=f"type:{t}", type=e, properties={"schema": True, "description": RELATIONS.get(e, "")}))
    return g

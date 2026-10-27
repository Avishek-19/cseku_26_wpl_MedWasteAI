export type WasteUnit = "kg" | "lb" | "l" | "pcs";

export type WasteStatus =
  | "reported"
  | "classified"
  | "risk_assessed"
  | "segregated"
  | "pickup_requested"
  | "pickup_assigned"
  | "collected"
  | "in_transit"
  | "destination_received"
  | "processing"
  | "recycled"
  | "treated"
  | "disposed"
  | "verified"
  | "completed";

export const WASTE_STATUS_LABELS: Record<WasteStatus, string> = {
  reported: "Reported",
  classified: "Classified",
  risk_assessed: "Risk assessed",
  segregated: "Segregated",
  pickup_requested: "Pickup requested",
  pickup_assigned: "Pickup assigned",
  collected: "Collected",
  in_transit: "In transit",
  destination_received: "Destination received",
  processing: "Processing",
  recycled: "Recycled",
  treated: "Treated",
  disposed: "Disposed",
  verified: "Verified",
  completed: "Completed",
};

export interface WasteCategory {
  id: string;
  code: string;
  name: string;
  description: string | null;
  is_recyclable: boolean;
}

export interface WasteAttachment {
  id: string;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  created_at: string;
}

export interface WasteRecord {
  id: string;
  waste_code: string;
  hospital_id: string;
  category: WasteCategory;
  quantity: string;
  unit: WasteUnit;
  description: string | null;
  generated_at: string;
  status: WasteStatus;
  created_at: string;
  updated_at: string;
  attachments: WasteAttachment[];
  received_quantity: string | null;
  received_at: string | null;
  assigned_facility_id?: string | null;
  assigned_facility_name?: string | null;
  processing_method?: string | null;
  route_id?: string | null;
  vehicle_id?: string | null;
}

export interface WasteRecordListResponse {
  items: WasteRecord[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export interface WasteRecordInput {
  category_id?: string;
  quantity: string;
  unit: WasteUnit;
  description?: string;
  generated_at?: string;
}

export type ClassificationConfidence = "high" | "medium" | "low";
export type ClassificationSource = "rule_engine" | "manual";

export interface RuleMatch {
  category_code: string;
  matched_keywords: string[];
}

export interface WasteClassification {
  id: string;
  waste_record_id: string;
  suggested_category: WasteCategory;
  source: ClassificationSource;
  confidence: ClassificationConfidence;
  matched_rules: RuleMatch[];
  explanation: string;
  notes: string | null;
  is_confirmed: boolean;
  confirmed_by: string | null;
  confirmed_at: string | null;
  processing_method: string | null;
  routing_status: string;
  routing_reason: string | null;
  decision_method: string;
  match_score: number | null;
  requires_human_verification: boolean;
  created_at: string;
}

export type RiskLevel = "low" | "medium" | "high" | "critical";
export type SuggestedHandling = "recycle" | "treat" | "dispose";
export type AssessmentSource = "rule_engine" | "manual";

export const RISK_LEVEL_LABELS: Record<RiskLevel, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

export const SUGGESTED_HANDLING_LABELS: Record<SuggestedHandling, string> = {
  recycle: "Recycle",
  treat: "Treat",
  dispose: "Dispose",
};

export interface WasteRiskAssessment {
  id: string;
  waste_record_id: string;
  risk_level: RiskLevel;
  recyclability_decision: boolean;
  suggested_handling: SuggestedHandling;
  source: AssessmentSource;
  factors: {
    base_risk_level?: string;
    quantity_escalated?: boolean;
    category_recyclable?: boolean;
  };
  explanation: string;
  notes: string | null;
  is_confirmed: boolean;
  confirmed_by: string | null;
  confirmed_at: string | null;
  created_at: string;
}

export type VehicleStatus = "available" | "reserved" | "on_route" | "maintenance";

export const VEHICLE_STATUS_LABELS: Record<VehicleStatus, string> = {
  available: "Available",
  reserved: "Reserved for pickup",
  on_route: "On route",
  maintenance: "Maintenance",
};

export interface Vehicle {
  id: string;
  vehicle_code: string;
  assigned_collector_id: string;
  organization_id: string | null;
  capacity_kg: string;
  status: VehicleStatus;
  location: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export type PickupPriority = "normal" | "urgent" | "emergency";
export type PickupStatus = "requested" | "assigned" | "collected" | "in_transit" | "cancelled";

export const PICKUP_PRIORITY_LABELS: Record<PickupPriority, string> = {
  normal: "Normal",
  urgent: "Urgent",
  emergency: "Emergency",
};

export const PICKUP_STATUS_LABELS: Record<PickupStatus, string> = {
  requested: "Requested",
  assigned: "Assigned",
  collected: "Collected",
  in_transit: "In transit",
  cancelled: "Cancelled",
};

export interface PickupRequest {
  id: string;
  hospital_id: string;
  priority: PickupPriority;
  status: PickupStatus;
  requested_pickup_at: string | null;
  scheduled_at: string | null;
  assigned_vehicle: Vehicle | null;
  hospital: {
    id: string;
    name: string;
    address_line: string;
    city: string;
    region: string;
    postal_code: string;
    latitude: string | number | null;
    longitude: string | number | null;
  };
  total_weight_kg: string | number | null;
  route_eligible: boolean;
  route_ineligibility_reason: string | null;
  assigned_collector_id: string | null;
  collected_at: string | null;
  cancelled_at: string | null;
  cancellation_reason: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  waste_records: WasteRecord[];
}

export interface PickupRequestListResponse {
  items: PickupRequest[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

export type DestinationType = "waste_processing_facility";

export interface MatchCandidate {
  id: string;
  name: string;
  city: string;
  score: number;
  is_verified: boolean;
  reasons: string[];
  processing_method?: string;
}

export interface MatchingRecord {
  id: string;
  waste_record_id: string;
  destination_type: DestinationType;
  candidates: MatchCandidate[];
  explanation: string;
  confirmed_facility_id: string | null;
  is_confirmed: boolean;
  confirmed_by: string | null;
  confirmed_at: string | null;
  processing_method: string | null;
  routing_status: string;
  routing_reason: string | null;
  decision_method: string;
  match_score: number | null;
  requires_human_verification: boolean;
  created_at: string;
}

export type WasteEventType =
  | "reported"
  | "classified"
  | "risk_assessed"
  | "matched"
  | "pickup_requested"
  | "pickup_assigned"
  | "pickup_cancelled"
  | "collected"
  | "in_transit"
  | "destination_received"
  | "processing"
  | "proof_submitted"
  | "verified"
  | "completed";

export const WASTE_EVENT_LABELS: Record<WasteEventType, string> = {
  reported: "Reported",
  classified: "Classified",
  risk_assessed: "Risk assessed",
  matched: "Destination matched",
  pickup_requested: "Pickup requested",
  pickup_assigned: "Pickup assigned",
  pickup_cancelled: "Pickup cancelled",
  collected: "Collected",
  in_transit: "In transit",
  destination_received: "Facility received",
  processing: "Processing",
  proof_submitted: "Processing proof submitted",
  verified: "Verified",
  completed: "Completed",
};

export interface EventActor {
  id: string;
  full_name: string;
  role: string;
}

export interface WasteEvent {
  id: string;
  waste_record_id: string;
  event_type: WasteEventType;
  status_snapshot: WasteStatus;
  actor: EventActor | null;
  quantity: string | null;
  notes: string | null;
  event_metadata: Record<string, unknown>;
  created_at: string;
}

export interface Notification {
  id: string;
  title: string;
  body: string;
  waste_record_id: string | null;
  is_read: boolean;
  created_at: string;
}

export interface NotificationListResponse {
  items: Notification[];
  unread_count: number;
}

export type IncidentType = "weight_discrepancy";
export type IncidentSeverity = "minor" | "major";

export interface Incident {
  id: string;
  waste_record_id: string;
  incident_type: IncidentType;
  severity: IncidentSeverity;
  description: string;
  is_resolved: boolean;
  created_at: string;
}

export interface ReceiveWasteResponse {
  waste_record_id: string;
  received_quantity: string;
  reported_quantity: string;
  variance_percent: string;
  incident: Incident | null;
}

export interface AIClassificationSuggestion {
  category_code: string;
  category_name: string;
  confidence: number;
  reasoning: string;
  requires_verification: boolean;
}

export interface AIRiskSuggestion {
  risk_level: RiskLevel;
  suggested_handling: SuggestedHandling;
  confidence: number;
  reasoning: string;
  requires_verification: boolean;
}

export interface AIRecyclabilitySuggestion {
  recyclable: boolean;
  confidence: number;
  reasoning: string;
  requires_verification: boolean;
}


export interface AIProcessingSuggestion {
  required_processing: string;
  acceptable_methods: string[];
  confidence: number;
  reasoning: string;
  requires_verification: boolean;
}

export interface AIImageAnalysis {
  status: string;
  model: string | null;
  observations: string;
  suggested_category: string | null;
  confidence: number | null;
  requires_verification: boolean;
}

export interface AIAnomalyAnalysis {
  status: string;
  is_anomaly: boolean;
  score: number;
  baseline_mean: number | null;
  baseline_median: number | null;
  message: string;
  requires_verification: boolean;
}

export interface AITrendPoint {
  period: string;
  quantity: number;
}

export interface AITrendPrediction {
  status: string;
  method: string;
  direction: string;
  next_period_quantity: number | null;
  points: AITrendPoint[];
  message: string;
  is_estimate: boolean;
}

export interface AIMatchingAssistance {
  status: string;
  recommendation: string | null;
  candidates: MatchCandidate[];
  explanation: string;
  requires_verification: boolean;
}

export interface AIAnalysisResponse {
  waste_record_id: string;
  generated_at: string;
  provider: string;
  model: string | null;
  disclaimer: string;
  classification: AIClassificationSuggestion;
  risk: AIRiskSuggestion;
  recyclability: AIRecyclabilitySuggestion;
  processing: AIProcessingSuggestion;
  image: AIImageAnalysis;
  anomaly: AIAnomalyAnalysis;
  trend: AITrendPrediction;
  matching: AIMatchingAssistance;
}

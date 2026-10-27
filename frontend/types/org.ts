import type { WasteCategory } from "./waste";

interface OrgProfileBase {
  id: string;
  user_id: string;
  name: string;
  registration_number: string;
  contact_person: string;
  phone: string;
  address_line: string;
  city: string;
  region: string;
  postal_code: string;
  capacity_kg: string;
  current_utilization_kg: string;
  is_verified: boolean;
  latitude?: number | null;
  longitude?: number | null;
  created_at: string;
  updated_at: string;
}

export type FacilityProfile = OrgProfileBase & {
  facility_type: string;
  processing_services: string[];
  other_services: string[];
  availability_status: "available" | "limited" | "unavailable";
};

export interface OrgProfileInput {
  name: string;
  registration_number: string;
  contact_person: string;
  phone: string;
  address_line: string;
  city: string;
  region: string;
  postal_code: string;
  capacity_kg: string;
  latitude?: number | null;
  longitude?: number | null;
  facility_type?: string;
  processing_services?: string[];
  other_services?: string[];
  availability_status?: "available" | "limited" | "unavailable";
  accepted_category_ids?: string[];
}

export interface OrgDashboardStats {
  profile_complete: boolean;
  is_verified: boolean;
  member_since: string;
  capacity_kg: string | null;
  current_utilization_kg: string | null;
  available_capacity_kg: string | null;
  utilization_percent: number | null;
  accepted_category_count: number;
  incoming_waste_count: number;
  processing_queue_count: number;
  matching_available: boolean;
  facility_type: string;
  processing_services: string[];
  other_services: string[];
  availability_status: "available" | "limited" | "unavailable";
}

export type { WasteCategory };

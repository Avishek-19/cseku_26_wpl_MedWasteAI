export interface HospitalProfile {
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
  bed_count: number | null;
  latitude: number | null;      
  longitude: number | null;
  is_verified: boolean;
  created_at: string;
  updated_at: string;
}

export interface HospitalProfileInput {
  name: string;
  registration_number: string;
  contact_person: string;
  phone: string;
  address_line: string;
  city: string;
  region: string;
  postal_code: string;
  bed_count: number | null;
  latitude: number | null;      
  longitude: number | null;
}

export interface HospitalDashboardStats {
  profile_complete: boolean;
  is_verified: boolean;
  member_since: string;
  total_waste_records: number;
  waste_tracking_available: boolean;
}

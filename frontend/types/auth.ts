export type UserRole = "hospital" | "collector" | "facility" | "admin";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: UserRole;
  is_active: boolean;
  is_verified: boolean;
  created_at: string;
}

export const ROLE_LABELS: Record<UserRole, string> = {
  hospital: "Hospital",
  collector: "Waste collector",
  facility: "Treatment facility",
  admin: "Administrator",
};

export type AnalyticsPoint = {
  label: string;
  value: number;
};

export type AnalyticsCategory = {
  name: string;
  batches: number;
  weight_kg: number;
  percentage: number;
};

export type AnalyticsResponse = {
  scope: string;
  period: "7d" | "30d" | "90d" | "12m";
  from_date: string;
  to_date: string;
  summary: {
    total_batches: number;
    tracked_weight_kg: number;
    recyclable_weight_kg: number;
    recycled_weight_kg: number;
    treated_weight_kg: number;
    disposed_weight_kg: number;
    recycling_rate: number;
    high_risk_batches: number;
    active_batches: number;
    completed_batches: number;
  };
  waste_trend: AnalyticsPoint[];
  category_distribution: AnalyticsCategory[];
  processing: AnalyticsPoint[];
  notes: string[];
  generated_at: string;
};

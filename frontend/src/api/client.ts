const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, init);
  if (!res.ok) {
    const text = await res.text();
    throw new ApiError(res.status, text || res.statusText);
  }
  return res.json();
}

function buildQs(params: Record<string, string | number | undefined | null>) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v != null && v !== "") qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : "";
}

// ---------- Documents ----------

export function uploadDocument(file: File) {
  const form = new FormData();
  form.append("file", file);
  return request<DocumentResponse>("/documents/upload", {
    method: "POST",
    body: form,
  });
}

export function getDocuments(params?: {
  skip?: number;
  limit?: number;
  status?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
  category?: string;
}) {
  return request<DocumentListItem[]>(
    `/documents${buildQs(params ?? {})}`,
  );
}

export function getDocumentCount(params?: {
  status?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
  category?: string;
}) {
  return request<{ count: number }>(
    `/documents/count${buildQs(params ?? {})}`,
  );
}

export function getDocument(id: string) {
  return request<DocumentResponse>(`/documents/${id}`);
}

export function updateDocument(id: string, data: Record<string, unknown>) {
  return request<DocumentResponse>(`/documents/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function updateItem(
  docId: string,
  itemId: string,
  data: Record<string, unknown>,
) {
  return request<DocumentResponse>(`/documents/${docId}/items/${itemId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function deleteItem(docId: string, itemId: string) {
  return request<DocumentResponse>(`/documents/${docId}/items/${itemId}`, {
    method: "DELETE",
  });
}

export function approveDocument(id: string) {
  return request<DocumentResponse>(`/documents/${id}/approve`, {
    method: "POST",
  });
}

export function reextractDocument(id: string) {
  return request<DocumentResponse>(`/documents/${id}/reextract`, {
    method: "POST",
  });
}

export function deleteDocument(id: string) {
  return request<{ message: string }>(`/documents/${id}`, {
    method: "DELETE",
  });
}

// ---------- Dashboard ----------

export function getDashboardStats() {
  return request<DashboardStats>("/dashboard/stats");
}

export function getDailySales(days = 30) {
  return request<DailySales[]>(`/dashboard/daily-sales?days=${days}`);
}

export function getTopMerchants(limit = 10) {
  return request<TopMerchant[]>(`/dashboard/top-merchants?limit=${limit}`);
}

export function getCategoryBreakdown() {
  return request<CategoryBreakdown[]>("/dashboard/category-breakdown");
}

export function getVatSummary(params?: {
  date_from?: string;
  date_to?: string;
}) {
  return request<VatSummaryResponse>(
    `/dashboard/vat-summary${buildQs(params ?? {})}`,
  );
}

export function getFraudSummary() {
  return request<FraudSummary>("/dashboard/fraud-summary");
}

export function getSpendingHeatmap(days = 90) {
  return request<HeatmapDay[]>(`/dashboard/spending-heatmap?days=${days}`);
}

export function getAiInsight() {
  return request<AiInsightResponse>("/dashboard/ai-insight");
}

export function getDocumentImageUrl(id: string) {
  return `${API_BASE}/documents/${id}/image`;
}

export function getExportUrl(params?: {
  date_from?: string;
  date_to?: string;
  merchant?: string;
}) {
  return `${API_BASE}/dashboard/export${buildQs(params ?? {})}`;
}

// ---------- Types ----------

export interface DocumentItemData {
  id: string;
  document_id: string;
  product_name_normalized: string | null;
  category: string | null;
  quantity: number | null;
  unit: string | null;
  unit_price: number | null;
  line_total: number | null;
  confidence: number | null;
  needs_review: boolean;
}

export interface DocumentResponse {
  id: string;
  filename: string;
  file_type: string;
  status: string;
  uploaded_at: string;
  processed_at: string | null;
  reviewed_at: string | null;
  confidence: number | null;
  needs_review: boolean;
  error_message: string | null;
  merchant_name: string | null;
  merchant_normalized: string | null;
  document_number: string | null;
  document_date: string | null;
  subtotal: number | null;
  discount: number | null;
  vat: number | null;
  grand_total: number | null;
  category: string | null;
  notes: string | null;
  fraud_flags: string | null;
  items: DocumentItemData[];
}

export interface DocumentListItem {
  id: string;
  filename: string;
  file_type: string;
  status: string;
  uploaded_at: string;
  merchant_name: string | null;
  merchant_normalized: string | null;
  grand_total: number | null;
  category: string | null;
  confidence: number | null;
  needs_review: boolean;
  item_count: number;
  fraud_flags: string | null;
}

export interface DashboardStats {
  total_documents: number;
  pending_review: number;
  reviewed: number;
  total_sales: number;
  avg_confidence: number;
  documents_today: number;
}

export interface DailySales {
  date: string;
  total: number;
  count: number;
}

export interface TopMerchant {
  merchant: string;
  total: number;
  count: number;
}

export interface CategoryBreakdown {
  category: string;
  total: number;
  count: number;
}

export interface VatMonthly {
  month: string;
  subtotal: number;
  vat: number;
  grand_total: number;
  count: number;
}

export interface VatSummaryResponse {
  months: VatMonthly[];
  totals: {
    subtotal: number;
    vat: number;
    grand_total: number;
    count: number;
  };
}

export interface FraudFlag {
  type: string;
  label: string;
  severity: "high" | "medium" | "low";
  detail: string;
}

export interface AiAnalysis {
  risk_score: number;
  risk_level: "high" | "medium" | "low";
  summary: string;
}

export interface FraudResult {
  flags: FraudFlag[];
  ai_analysis: AiAnalysis | null;
}

export interface FraudFlaggedDoc {
  id: string;
  filename: string;
  merchant_name: string | null;
  grand_total: number | null;
  document_date: string | null;
  severity: "high" | "medium" | "low";
  flags: string[];
  flag_count: number;
}

export interface FraudSummary {
  total_flagged: number;
  by_severity: { high: number; medium: number; low: number };
  by_type: { type: string; count: number }[];
  documents: FraudFlaggedDoc[];
}

export interface HeatmapDay {
  date: string;
  total: number;
  count: number;
}

export interface AiInsightResponse {
  headline: string;
  insights: string[];
  risks: string[];
  opportunities: string[];
}

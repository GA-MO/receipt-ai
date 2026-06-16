const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, init);
  if (!res.ok) {
    const text = await res.text();
    let message = text || res.statusText;
    let detail: unknown;
    try {
      const parsed = JSON.parse(text);
      if (parsed && typeof parsed === "object" && "detail" in parsed) {
        detail = (parsed as { detail: unknown }).detail;
        if (typeof detail === "string") message = detail;
        else if (
          detail &&
          typeof detail === "object" &&
          "message" in detail &&
          typeof (detail as { message: unknown }).message === "string"
        ) {
          message = (detail as { message: string }).message;
        }
      }
    } catch {
      // body wasn't JSON — fall through with raw text
    }
    throw new ApiError(res.status, message, detail);
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

export function getDocuments(params?: {
  skip?: number;
  limit?: number;
  status?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
  category?: string;
  sort_by?: string;
  sort_dir?: string;
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

export function createItem(docId: string, data: Record<string, unknown>) {
  return request<DocumentResponse>(`/documents/${docId}/items`, {
    method: "POST",
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

export function bulkApproveDocuments(ids: string[]) {
  return request<BulkActionResult>(`/documents/bulk/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

export function bulkDeleteDocuments(ids: string[]) {
  return request<BulkActionResult>(`/documents/bulk/delete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

export function bulkRestoreDocuments(ids: string[]) {
  return request<BulkActionResult>(`/documents/bulk/restore`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

export function bulkPurgeDocuments(ids: string[]) {
  return request<BulkActionResult>(`/documents/bulk/purge`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

export function restoreDocument(id: string) {
  return request<DocumentResponse>(`/documents/${id}/restore`, { method: "POST" });
}

export function purgeDocument(id: string) {
  return request<{ message: string }>(`/documents/${id}/purge`, { method: "POST" });
}

export function getTrash(params?: { skip?: number; limit?: number }) {
  return request<DocumentListItem[]>(`/documents/trash${buildQs(params ?? {})}`);
}

export function getTrashCount() {
  return request<{ count: number }>(`/documents/trash/count`);
}

// ---------- Stores ----------

export interface StoreListItem {
  id: string;
  code: string | null;
  name: string;
  normalized_name: string | null;
  address: string | null;
  notes: string | null;
  active: boolean;
  created_at: string;
  updated_at: string;
  visit_count: number;
}

export interface StoreInput {
  name: string;
  code?: string | null;
  normalized_name?: string | null;
  address?: string | null;
  notes?: string | null;
}

export interface StorePatch extends Partial<StoreInput> {
  active?: boolean;
}

export function getStores(params?: { q?: string; include_inactive?: boolean }) {
  const qs: Record<string, string | number | undefined | null> = {};
  if (params?.q) qs.q = params.q;
  if (params?.include_inactive) qs.include_inactive = "true";
  return request<StoreListItem[]>(`/stores${buildQs(qs)}`);
}

export function getStore(id: string) {
  return request<StoreListItem>(`/stores/${id}`);
}

export function createStore(body: StoreInput) {
  return request<StoreListItem>("/stores", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function updateStore(id: string, body: StorePatch) {
  return request<StoreListItem>(`/stores/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteStore(id: string) {
  return request<{ id: string; status: "deleted" | "deactivated"; visit_count?: number }>(
    `/stores/${id}`,
    { method: "DELETE" },
  );
}

// ---------- Visits ----------

export interface VisitListItem {
  id: string;
  store_id: string | null;
  store_key: string | null;
  store_label: string | null;
  report_period: string | null;
  rep_name: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  document_count: number;
  reviewed_count: number;
  earliest_doc_date: string | null;
  latest_doc_date: string | null;
}

export interface VisitAggregateRow {
  product_code: string | null;
  display_name: string;
  manufacturer: string | null;
  is_catalog_match: boolean;
  total_quantity: number;
  unit: string | null;
  source_doc_ids: string[];
  source_count: number;
  units_seen: string[];
}

export interface VisitDetail {
  id: string;
  store_id: string | null;
  store_key: string | null;
  store_label: string | null;
  report_period: string | null;
  rep_name: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
  documents: DocumentListItem[];
  aggregate: VisitAggregateRow[];
  reviewed_count: number;
}

export interface VisitUploadResult {
  visit_id: string;
  document_ids: string[];
  duplicates: { filename: string; existing_document_id: string; existing_visit_id: string | null }[];
  failures: { filename: string; detail: string }[];
}

export function createVisit(body: {
  store_id?: string;
  store_label?: string;
  report_period?: string;
  rep_name?: string;
  notes?: string;
}) {
  return request<VisitListItem>("/visits", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getVisits(params?: {
  skip?: number;
  limit?: number;
  store_id?: string;
  store_key?: string;
  rep_name?: string;
}) {
  return request<VisitListItem[]>(`/visits${buildQs(params ?? {})}`);
}

export function getVisit(id: string, params?: { date_from?: string; date_to?: string }) {
  return request<VisitDetail>(`/visits/${id}${buildQs(params ?? {})}`);
}

export function updateVisit(
  id: string,
  body: {
    store_id?: string;
    store_label?: string;
    store_key?: string;
    report_period?: string;
    rep_name?: string;
    notes?: string;
  },
) {
  return request<VisitListItem>(`/visits/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteVisit(id: string) {
  return request<{ id: string; deleted_at: string }>(`/visits/${id}`, { method: "DELETE" });
}

export function uploadDocumentsToVisit(visitId: string, files: File[]) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return request<VisitUploadResult>(`/visits/${visitId}/documents`, {
    method: "POST",
    body: form,
  });
}

export function recomputeVisitLabel(id: string) {
  return request<{ id: string; store_key: string | null; store_label: string | null }>(
    `/visits/${id}/recompute-label`,
    { method: "POST" },
  );
}

// ---------- Inbox / Dashboard (Drop & Review) ----------

export interface InboxUploadResult {
  document_ids: string[];
  duplicates: { filename: string; existing_document_id: string; existing_visit_id: string | null }[];
  failures: { filename: string; detail: string }[];
}

export interface DashboardVisit extends VisitListItem {
  new_doc_count: number;
  needs_review_count: number;
  last_reviewed_at: string | null;
}

export interface DashboardResponse {
  month: string | null;
  available_months: string[];
  orphans: DocumentListItem[];
  unknown_stores: DocumentListItem[];
  non_receipts: DocumentListItem[];
  errors: DocumentListItem[];
  processing: DocumentListItem[];
  visits: DashboardVisit[];
  counts: {
    orphans: number;
    unknown_stores: number;
    non_receipts: number;
    errors: number;
    processing: number;
    visits: number;
    attention: number;
  };
}

export function uploadInbox(files: File[]) {
  const form = new FormData();
  for (const f of files) form.append("files", f);
  return request<InboxUploadResult>(`/inbox`, {
    method: "POST",
    body: form,
  });
}

export function getDashboard(month?: string | null) {
  const qs = month ? `?month=${encodeURIComponent(month)}` : "";
  return request<DashboardResponse>(`/inbox/dashboard${qs}`);
}

export function nameOrphan(docId: string, merchantName: string) {
  return request<DocumentListItem>(`/inbox/documents/${docId}/name`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ merchant_name: merchantName }),
  });
}

export function assignStoreToDoc(docId: string, storeId: string) {
  return request<DocumentListItem>(`/inbox/documents/${docId}/assign-store`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ store_id: storeId }),
  });
}

export function createStoreFromDoc(
  docId: string,
  payload: { name: string; code?: string; normalized_name?: string },
) {
  return request<DocumentListItem>(`/inbox/documents/${docId}/create-store`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function discardInboxDoc(docId: string) {
  return request<{ id: string; deleted_at: string }>(`/inbox/documents/${docId}`, {
    method: "DELETE",
  });
}

export function markVisitReviewed(visitId: string) {
  return request<{ id: string; last_reviewed_at: string }>(
    `/inbox/visits/${visitId}/mark-reviewed`,
    { method: "POST" },
  );
}

export function purgeNonReceipts(olderThanDays = 7) {
  return request<{ purged: number; cutoff: string }>(
    `/inbox/non-receipts/purge?older_than_days=${olderThanDays}`,
    { method: "POST" },
  );
}

export function getDocumentImageUrl(id: string) {
  return `${API_BASE}/documents/${id}/image`;
}

export function getDocumentHistory(id: string, limit = 200) {
  return request<DocumentEventItem[]>(
    `/documents/${id}/history?limit=${limit}`,
  );
}

// ---------- Learned aliases ----------

export function getAliases(limit = 100) {
  return request<MerchantAliasItem[]>(`/aliases?limit=${limit}`);
}

export function getProductAliases(limit = 100) {
  return request<MerchantAliasItem[]>(`/aliases/products?limit=${limit}`);
}

export function getAliasStats() {
  return request<AliasStats>("/aliases/stats");
}

export function deleteAlias(id: string) {
  return request<{ status: string }>(`/aliases/${id}`, { method: "DELETE" });
}

export function deleteProductAlias(id: string) {
  return request<{ status: string }>(`/aliases/products/${id}`, { method: "DELETE" });
}

// ---------- Autocomplete ----------

export type AutocompleteKind = "merchant" | "product";

export interface AutocompleteOption {
  value: string;
  score: number;
  code?: string | null;
}

export function getAutocomplete(
  kind: AutocompleteKind,
  q: string = "",
  limit: number = 20,
) {
  return request<AutocompleteOption[]>(
    `/autocomplete${buildQs({ kind, q, limit })}`,
  );
}

// ---------- Types ----------

export interface DocumentItemData {
  id: string;
  document_id: string;
  product_name_raw: string | null;
  product_name_normalized: string | null;
  product_code: string | null;
  category: string | null;
  quantity: number | null;
  unit: string | null;
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
  category: string | null;
  notes: string | null;
  items: DocumentItemData[];
  visit_id: string | null;
}

export interface DocumentListItem {
  id: string;
  filename: string;
  file_type: string;
  status: string;
  uploaded_at: string;
  merchant_name: string | null;
  merchant_normalized: string | null;
  document_date: string | null;
  category: string | null;
  confidence: number | null;
  needs_review: boolean;
  item_count: number;
  visit_id: string | null;
  period_mismatch: boolean;
  store_mismatch: boolean;
}

export interface BulkActionResult {
  succeeded: number;
  failed: number;
  failed_ids: string[];
}

export interface MerchantAliasItem {
  id: string;
  source_text: string;
  canonical_name: string;
  category: string | null;
  hit_count: number;
}

export interface DocumentEventItem {
  id: string;
  event_type: string;
  actor: string;
  payload: Record<string, unknown> | null;
  created_at: string | null;
}

export interface AliasKindStats {
  total_aliases: number;
  total_hits: number;
}

export interface AliasStats {
  total_aliases: number;
  total_hits: number;
  merchants: AliasKindStats;
  products: AliasKindStats;
}


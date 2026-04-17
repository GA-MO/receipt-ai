/**
 * React Query hooks — one place for query keys, fetchers, and cache invalidation.
 *
 * Pattern:
 *   const { data: doc, isPending, error } = useDocument(id);
 *   const approve = useApproveDocument();
 *   await approve.mutateAsync(id);
 *
 * Mutations automatically invalidate relevant queries so lists/dashboards
 * refresh without manual refetch calls.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from "@tanstack/react-query";

import {
  approveDocument,
  deleteDocument,
  deleteItem,
  getAiInsight,
  getCategoryBreakdown,
  getDailySales,
  getDashboardStats,
  getDocument,
  getDocumentCount,
  getDocuments,
  getFraudSummary,
  getSpendingHeatmap,
  getTopMerchants,
  getVatSummary,
  reextractDocument,
  updateDocument,
  updateItem,
  uploadDocument,
  type DocumentResponse,
} from "./client";

// ---------- Query keys ----------

export const qk = {
  documents: (params?: Record<string, unknown>) => ["documents", params] as const,
  documentCount: (params?: Record<string, unknown>) =>
    ["documents", "count", params] as const,
  document: (id: string) => ["documents", id] as const,
  dashboard: {
    stats: ["dashboard", "stats"] as const,
    dailySales: (days: number) => ["dashboard", "dailySales", days] as const,
    topMerchants: (limit: number) => ["dashboard", "topMerchants", limit] as const,
    categories: (mode?: string) => ["dashboard", "categories", mode] as const,
    vat: (params?: Record<string, unknown>) => ["dashboard", "vat", params] as const,
    fraud: ["dashboard", "fraud"] as const,
    heatmap: (days: number) => ["dashboard", "heatmap", days] as const,
    insight: ["dashboard", "insight"] as const,
  },
};

// ---------- Invalidation helper ----------

function useInvalidate() {
  const qc = useQueryClient();
  return {
    afterMutation: (docId?: string) => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      if (docId) qc.invalidateQueries({ queryKey: qk.document(docId) });
    },
  };
}

// ---------- Documents ----------

export interface DocumentListFilters {
  skip?: number;
  limit?: number;
  status?: string;
  search?: string;
  date_from?: string;
  date_to?: string;
  category?: string;
}

export function useDocuments(filters: DocumentListFilters = {}) {
  return useQuery({
    queryKey: qk.documents(filters as Record<string, unknown>),
    queryFn: () => getDocuments(filters),
  });
}

export function useDocumentCount(
  filters: Omit<DocumentListFilters, "skip" | "limit"> = {},
) {
  return useQuery({
    queryKey: qk.documentCount(filters as Record<string, unknown>),
    queryFn: () => getDocumentCount(filters),
  });
}

export function useDocument(
  id: string | undefined,
  options?: Partial<UseQueryOptions<DocumentResponse>>,
) {
  return useQuery({
    queryKey: qk.document(id ?? ""),
    queryFn: () => getDocument(id!),
    enabled: !!id,
    ...options,
  });
}

export function useUploadDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (file: File) => uploadDocument(file),
    onSuccess: () => invalidate.afterMutation(),
  });
}

export function useUpdateDocument(id: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) => updateDocument(id, data),
    onSuccess: () => invalidate.afterMutation(id),
  });
}

export function useUpdateItem(docId: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: ({ itemId, data }: { itemId: string; data: Record<string, unknown> }) =>
      updateItem(docId, itemId, data),
    onSuccess: () => invalidate.afterMutation(docId),
  });
}

export function useDeleteItem(docId: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (itemId: string) => deleteItem(docId, itemId),
    onSuccess: () => invalidate.afterMutation(docId),
  });
}

export function useApproveDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => approveDocument(id),
    onSuccess: (_data, id) => invalidate.afterMutation(id),
  });
}

export function useReextractDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => reextractDocument(id),
    onSuccess: (_data, id) => invalidate.afterMutation(id),
  });
}

export function useDeleteDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: () => invalidate.afterMutation(),
  });
}

// ---------- Dashboard ----------

export function useDashboardStats() {
  return useQuery({
    queryKey: qk.dashboard.stats,
    queryFn: getDashboardStats,
  });
}

export function useDailySales(days = 30) {
  return useQuery({
    queryKey: qk.dashboard.dailySales(days),
    queryFn: () => getDailySales(days),
  });
}

export function useTopMerchants(limit = 10) {
  return useQuery({
    queryKey: qk.dashboard.topMerchants(limit),
    queryFn: () => getTopMerchants(limit),
  });
}

export function useCategoryBreakdown() {
  return useQuery({
    queryKey: qk.dashboard.categories(),
    queryFn: getCategoryBreakdown,
  });
}

export function useVatSummary(params?: { date_from?: string; date_to?: string }) {
  return useQuery({
    queryKey: qk.dashboard.vat(params as Record<string, unknown>),
    queryFn: () => getVatSummary(params),
  });
}

export function useFraudSummary() {
  return useQuery({
    queryKey: qk.dashboard.fraud,
    queryFn: getFraudSummary,
  });
}

export function useSpendingHeatmap(days = 90) {
  return useQuery({
    queryKey: qk.dashboard.heatmap(days),
    queryFn: () => getSpendingHeatmap(days),
  });
}

export function useAiInsight() {
  return useMutation({
    mutationFn: getAiInsight,
  });
}

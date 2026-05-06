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
  bulkApproveDocuments,
  bulkDeleteDocuments,
  bulkPurgeDocuments,
  bulkRestoreDocuments,
  createItem,
  deleteAlias,
  deleteDocument,
  deleteItem,
  deleteProductAlias,
  getAutocomplete,
  getAiInsight,
  getAliasStats,
  getAliases,
  getProductAliases,
  getCatalogGaps,
  getCategoryBreakdown,
  getDailySales,
  getDashboardStats,
  getTypoRecoveries,
  getDocument,
  getDocumentCount,
  getDocumentHistory,
  getDocuments,
  getFraudSummary,
  getPeriodComparison,
  getSpendingHeatmap,
  getTopMerchants,
  getTopProducts,
  getTrash,
  getTrashCount,
  getVatSummary,
  purgeDocument,
  reextractDocument,
  restoreDocument,
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
    topProducts: (limit: number) => ["dashboard", "topProducts", limit] as const,
    categories: (mode?: string) => ["dashboard", "categories", mode] as const,
    vat: (params?: Record<string, unknown>) => ["dashboard", "vat", params] as const,
    fraud: ["dashboard", "fraud"] as const,
    heatmap: (days: number) => ["dashboard", "heatmap", days] as const,
    insight: ["dashboard", "insight"] as const,
    period: (period: string) => ["dashboard", "period", period] as const,
    catalogGaps: (days: number) => ["dashboard", "catalogGaps", days] as const,
    typoRecoveries: (days: number) => ["dashboard", "typoRecoveries", days] as const,
  },
  aliases: {
    list: (limit: number) => ["aliases", "list", limit] as const,
    products: (limit: number) => ["aliases", "products", limit] as const,
    stats: ["aliases", "stats"] as const,
  },
};

// ---------- Invalidation helper ----------

function useInvalidate() {
  const qc = useQueryClient();
  return {
    afterMutation: (docId?: string) => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      qc.invalidateQueries({ queryKey: ["dashboard"] });
      qc.invalidateQueries({ queryKey: ["trash"] });
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
  sort_by?: string;
  sort_dir?: string;
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

export function useDocumentHistory(id: string | undefined) {
  return useQuery({
    queryKey: ["documents", id, "history"] as const,
    queryFn: () => getDocumentHistory(id!),
    enabled: !!id,
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

export function useCreateItem(docId: string) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (data: Record<string, unknown>) => createItem(docId, data),
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

export function useBulkApprove() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (ids: string[]) => bulkApproveDocuments(ids),
    onSuccess: () => invalidate.afterMutation(),
  });
}

export function useBulkDelete() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (ids: string[]) => bulkDeleteDocuments(ids),
    onSuccess: () => invalidate.afterMutation(),
  });
}

export function useBulkRestore() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (ids: string[]) => bulkRestoreDocuments(ids),
    onSuccess: () => invalidate.afterMutation(),
  });
}

export function useBulkPurge() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (ids: string[]) => bulkPurgeDocuments(ids),
    onSuccess: () => invalidate.afterMutation(),
  });
}

export function useRestoreDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => restoreDocument(id),
    onSuccess: (_d, id) => invalidate.afterMutation(id),
  });
}

export function usePurgeDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: (id: string) => purgeDocument(id),
    onSuccess: () => invalidate.afterMutation(),
  });
}

export function useTrash(params?: { skip?: number; limit?: number }) {
  return useQuery({
    queryKey: ["trash", params] as const,
    queryFn: () => getTrash(params),
  });
}

export function useTrashCount() {
  return useQuery({
    queryKey: ["trash", "count"] as const,
    queryFn: getTrashCount,
    refetchInterval: 30_000,
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

export function useTopProducts(
  limit = 10,
  params?: { catalog_only?: boolean },
) {
  return useQuery({
    queryKey: ["dashboard", "topProducts", limit, params?.catalog_only] as const,
    queryFn: () => getTopProducts(limit, params),
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

export function usePeriodComparison(period: "7d" | "30d" | "month" | "year" = "month") {
  return useQuery({
    queryKey: qk.dashboard.period(period),
    queryFn: () => getPeriodComparison(period),
  });
}

export function useAiInsight() {
  return useMutation({
    mutationFn: getAiInsight,
  });
}

export function useCatalogGaps(days = 30) {
  return useQuery({
    queryKey: qk.dashboard.catalogGaps(days),
    queryFn: () => getCatalogGaps(days, 50),
    refetchInterval: 60_000,
  });
}

export function useTypoRecoveries(days = 30) {
  return useQuery({
    queryKey: qk.dashboard.typoRecoveries(days),
    queryFn: () => getTypoRecoveries(days, 50),
    refetchInterval: 60_000,
  });
}

// ---------- Learned aliases ----------

function useInvalidateAliases() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: ["aliases"] });
}

export function useAliases(limit = 100) {
  return useQuery({
    queryKey: qk.aliases.list(limit),
    queryFn: () => getAliases(limit),
  });
}

export function useProductAliases(limit = 100) {
  return useQuery({
    queryKey: qk.aliases.products(limit),
    queryFn: () => getProductAliases(limit),
  });
}

export function useAliasStats() {
  return useQuery({
    queryKey: qk.aliases.stats,
    queryFn: getAliasStats,
    refetchInterval: 30_000,
  });
}

export function useDeleteAlias() {
  const invalidate = useInvalidateAliases();
  return useMutation({
    mutationFn: (id: string) => deleteAlias(id),
    onSuccess: () => invalidate(),
  });
}

export function useDeleteProductAlias() {
  const invalidate = useInvalidateAliases();
  return useMutation({
    mutationFn: (id: string) => deleteProductAlias(id),
    onSuccess: () => invalidate(),
  });
}

// ---------- Autocomplete ----------

export function useAutocomplete(
  kind: "merchant" | "product",
  q: string = "",
  limit: number = 20,
) {
  return useQuery({
    queryKey: ["autocomplete", kind, q, limit] as const,
    queryFn: () => getAutocomplete(kind, q, limit),
    staleTime: 60_000,
  });
}

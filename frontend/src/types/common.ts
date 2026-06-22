export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number | null;
  offset: number;
  /**
   * Jobs list only: count of jobs still hidden while their people pre-warm
   * runs. While > 0 the feed polls so newly warmed jobs appear as they're ready.
   */
  warming_count?: number;
}

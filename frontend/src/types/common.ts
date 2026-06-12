export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number | null;
  offset: number;
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { InterviewPrepBrief, InterviewPrepUpdate } from '@/types';

const key = (jobId: string) => ['interview-prep', jobId];

export function useInterviewPrep(jobId: string | undefined, enabled: boolean = true) {
  return useQuery({
    queryKey: key(jobId ?? 'none'),
    queryFn: async () => {
      try {
        return await api.get<InterviewPrepBrief>(
          `/api/jobs/${jobId}/interview-prep`
        );
      } catch (err) {
        if (err instanceof Error && /not found/i.test(err.message)) {
          return null;
        }
        throw err;
      }
    },
    enabled: Boolean(jobId) && enabled,
    staleTime: 60 * 1000,
  });
}

export function useGenerateInterviewPrep(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (regenerate: boolean = false) =>
      api.post<InterviewPrepBrief>(`/api/jobs/${jobId}/interview-prep`, {
        regenerate,
      }),
    onSuccess: (data) => {
      qc.setQueryData(key(jobId), data);
    },
  });
}

export function useUpdateInterviewPrep(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: InterviewPrepUpdate) =>
      api.patch<InterviewPrepBrief>(
        `/api/jobs/${jobId}/interview-prep`,
        payload
      ),
    onSuccess: (data) => {
      qc.setQueryData(key(jobId), data);
    },
  });
}

export function useDeleteInterviewPrep(jobId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api.delete<{ ok: boolean; deleted: boolean }>(
        `/api/jobs/${jobId}/interview-prep`
      ),
    onSuccess: () => {
      qc.setQueryData(key(jobId), null);
    },
  });
}

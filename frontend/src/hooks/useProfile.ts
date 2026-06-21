import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { Profile } from '@/types';

export function useProfile() {
  return useQuery({
    queryKey: ['profile'],
    queryFn: () => api.get<Profile>('/api/profile'),
  });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (data: Partial<Profile>) => api.put<Profile>('/api/profile', data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] });
    },
  });
}

export function useUploadResume() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async (file: File) => {
      const arrayBuffer = await file.arrayBuffer();
      const bytes = new Uint8Array(arrayBuffer);
      let binary = '';
      const chunkSize = 0x8000;
      for (let index = 0; index < bytes.length; index += chunkSize) {
        const chunk = bytes.subarray(index, index + chunkSize);
        binary += String.fromCharCode(...chunk);
      }
      const fileBase64 = btoa(binary);

      const inferredType =
        file.type ||
        (file.name.toLowerCase().endsWith('.docx')
          ? 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
          : 'application/pdf');

      return api.post<Profile>('/api/profile/resume-json', {
        filename: file.name,
        content_type: inferredType,
        file_base64: fileBase64,
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['profile'] });
    },
  });
}

export function getProfileCompletion(profile: Profile | undefined): {
  percentage: number;
  missing: string[];
} {
  if (!profile) return { percentage: 0, missing: ['Everything'] };

  const checks: { label: string; done: boolean }[] = [
    { label: 'Full name', done: !!profile.full_name },
    { label: 'Bio', done: !!profile.bio },
    { label: 'Goals', done: !!profile.goals?.length },
    { label: 'Tone', done: !!profile.tone },
    { label: 'Resume', done: !!profile.resume_parsed },
    { label: 'Target industries', done: !!profile.target_industries?.length },
    { label: 'Target roles', done: !!profile.target_roles?.length },
    { label: 'LinkedIn URL', done: !!profile.linkedin_url },
  ];

  const completed = checks.filter((c) => c.done).length;
  const missing = checks.filter((c) => !c.done).map((c) => c.label);

  return {
    percentage: Math.round((completed / checks.length) * 100),
    missing,
  };
}

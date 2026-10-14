import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { pollInterval } from "../lib/status";
import { api } from "./client";
import type {
  AdminUser,
  GuestTask,
  Me,
  Quota,
  RoundRequest,
  SettingsView,
  Task,
  TaskPage,
} from "./types";

export const qk = {
  me: ["me"] as const,
  tasks: ["tasks"] as const,
  task: (id: string) => ["task", id] as const,
  guestTask: (id: string | null) => ["guest-task", id] as const,
  quota: ["guest-quota"] as const,
  users: ["admin-users"] as const,
  settings: ["admin-settings"] as const,
};

export function useMe() {
  return useQuery({ queryKey: qk.me, queryFn: () => api<Me>("/api/me") });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      api<Me>("/api/auth/login", { json: body }),
    onSuccess: (me) => qc.setQueryData(qk.me, me),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
    onSuccess: () => qc.clear(),
  });
}

export function useTask(id: string) {
  return useQuery({
    queryKey: qk.task(id),
    queryFn: () => api<Task>(`/api/tasks/${id}`),
    refetchInterval: (query) => pollInterval(query.state.data),
  });
}

export function useTasks(limit = 20) {
  return useInfiniteQuery({
    queryKey: [...qk.tasks, limit],
    queryFn: ({ pageParam }) =>
      api<TaskPage>(
        `/api/tasks?limit=${limit}${pageParam ? `&cursor=${encodeURIComponent(pageParam)}` : ""}`,
      ),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
}

function useTaskMutation<V>(id: string, fn: (variables: V) => Promise<Task>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (task) => {
      qc.setQueryData(qk.task(id), task);
      void qc.invalidateQueries({ queryKey: qk.tasks });
      void qc.invalidateQueries({ queryKey: qk.me });
    },
    // A rejected action (e.g. 409 because another tab started a round) means our view is stale.
    onError: () => {
      void qc.invalidateQueries({ queryKey: qk.task(id) });
    },
  });
}

export const useConfirmText = (id: string) =>
  useTaskMutation(id, (text: string) =>
    api<Task>(`/api/tasks/${id}/text`, { method: "PUT", json: { confirmed_text: text } }),
  );

export const useRetryTranscribe = (id: string) =>
  useTaskMutation<void>(id, () => api<Task>(`/api/tasks/${id}/transcribe`, { method: "POST" }));

export const useCreateRound = (id: string) =>
  useTaskMutation(id, (request: RoundRequest) => api<Task>(`/api/tasks/${id}/rounds`, { json: request }));

export const useRetryRound = (id: string) =>
  useTaskMutation(id, (seq: number) =>
    api<Task>(`/api/tasks/${id}/rounds/${seq}/retry`, { method: "POST" }),
  );

export const useSetFinal = (id: string) =>
  useTaskMutation(id, (roundId: number) =>
    api<Task>(`/api/tasks/${id}/final`, { json: { round_id: roundId } }),
  );

export function useUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<Task>("/api/tasks", { form });
    },
    onSuccess: (task) => {
      qc.setQueryData(qk.task(task.id), task);
      void qc.invalidateQueries({ queryKey: qk.tasks });
    },
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (taskId: string) => api<void>(`/api/tasks/${taskId}`, { method: "DELETE" }),
    onSuccess: (_data, taskId) => {
      qc.removeQueries({ queryKey: qk.task(taskId) });
      void qc.invalidateQueries({ queryKey: qk.tasks });
    },
  });
}

export function useGuestQuota() {
  return useQuery({ queryKey: qk.quota, queryFn: () => api<Quota>("/api/guest/quota") });
}

export function useGuestTask(id: string | null) {
  return useQuery({
    queryKey: qk.guestTask(id),
    queryFn: () => api<GuestTask>(`/api/guest/tasks/${id}`),
    enabled: id !== null,
    refetchInterval: (query) => pollInterval(query.state.data),
  });
}

export function useGuestUpload() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, prompt }: { file: File; prompt: string }) => {
      const form = new FormData();
      form.append("file", file);
      if (prompt.trim()) form.append("prompt", prompt.trim());
      return api<GuestTask>("/api/guest/tasks", { form });
    },
    onSuccess: (task) => {
      qc.setQueryData(qk.guestTask(task.id), task);
      void qc.invalidateQueries({ queryKey: qk.quota });
    },
    onError: () => {
      void qc.invalidateQueries({ queryKey: qk.quota });
    },
  });
}

export function useAdminUsers() {
  return useQuery({ queryKey: qk.users, queryFn: () => api<AdminUser[]>("/api/admin/users") });
}

export interface NewUser {
  username: string;
  password: string;
  role: "admin" | "user";
  daily_quota: number | null;
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: NewUser) => api<AdminUser>("/api/admin/users", { json: body }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.users });
    },
  });
}

export interface UserPatch {
  id: number;
  password?: string;
  role?: "admin" | "user";
  disabled?: boolean;
  daily_quota?: number;
}

export function usePatchUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...patch }: UserPatch) =>
      api<AdminUser>(`/api/admin/users/${id}`, { method: "PATCH", json: patch }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: qk.users });
    },
  });
}

export function useAdminSettings() {
  return useQuery({ queryKey: qk.settings, queryFn: () => api<SettingsView>("/api/admin/settings") });
}

export function usePatchSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (changes: Record<string, string | number>) =>
      api<SettingsView>("/api/admin/settings", { method: "PATCH", json: changes }),
    onSuccess: (view) => qc.setQueryData(qk.settings, view),
  });
}

import { request } from "./_client";
import type { Project, ProjectReadiness } from "./types";

export const projects = {
  list: () => request<Project[]>("/projects"),
  get: (id: string) => request<Project>(`/projects/${id}`),
  create: (data: Partial<Project>) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Project>) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" }),
  readiness: (id: string) => request<ProjectReadiness>(`/projects/${id}/readiness`),
  requestAccess: (data: { email: string; description: string; message: string }) =>
    request<{ ok: boolean }>("/projects/access-requests", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

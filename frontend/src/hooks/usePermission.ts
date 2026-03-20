import { useAppStore } from "@/stores/app-store";

export type ProjectRole = "owner" | "editor" | "viewer";

interface PermissionResult {
  role: ProjectRole | null;
  isOwner: boolean;
  canDelete: boolean;
  canEdit: boolean;
  canManageMembers: boolean;
}

export function usePermission(): PermissionResult {
  const userRole = useAppStore((s) => s.userRole) as ProjectRole | null;

  return {
    role: userRole,
    isOwner: userRole === "owner",
    canDelete: userRole === "owner",
    canEdit: userRole === "owner" || userRole === "editor",
    canManageMembers: userRole === "owner",
  };
}

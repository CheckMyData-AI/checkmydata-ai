"use client";

import { FormModal } from "@/components/ui/FormModal";
import { ResendVerificationButton } from "@/components/auth/ResendVerificationButton";
import { useAuthStore } from "@/stores/auth-store";

/**
 * Shown when an account tries to create a project before verifying its email.
 *
 * `can_create_projects` defaults to false and is granted by `verify_email`
 * (`auth_service.py`) — so an unverified user is one click from being able to
 * create, and was being told to wait for an administrator instead. The backend has
 * distinguished the two causes since F-PROJ-01; this is the interface catching up.
 */
export function VerifyEmailNeededModal({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const email = useAuthStore((s) => s.user?.email);

  return (
    <FormModal open={open} onClose={onClose} title="Verify your email to continue">
      <div className="space-y-4">
        <p className="text-sm text-text-secondary leading-relaxed">
          Creating a project needs a verified address. We sent a link to{" "}
          <strong className="text-text-primary">{email}</strong> — click it and this
          unlocks straight away. No approval, no waiting on anyone.
        </p>
        <p className="text-xs text-text-muted leading-relaxed">
          Nothing arrived? Check spam, then send it again.
        </p>
        <ResendVerificationButton className={"px-5 py-2 rounded-lg bg-primary hover:bg-primary/92 text-primary-foreground text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed w-full"} />
      </div>
    </FormModal>
  );
}

"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth-store";
import { toast } from "@/stores/toast-store";
import { FormModal } from "@/components/ui/FormModal";
import { Icon } from "@/components/ui/Icon";

const inputCls =
  "w-full bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors";

interface RequestAccessModalProps {
  open: boolean;
  onClose: () => void;
}

export function RequestAccessModal({ open, onClose }: RequestAccessModalProps) {
  const user = useAuthStore((s) => s.user);
  const [email, setEmail] = useState(user?.email ?? "");
  const [description, setDescription] = useState("");
  const [message, setMessage] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const canSubmit = email.trim() && description.trim() && message.trim() && !submitting;

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    try {
      await api.projects.requestAccess({
        email: email.trim(),
        description: description.trim(),
        message: message.trim(),
      });
      setSubmitted(true);
      toast("Request sent! We'll get back to you soon.", "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to send request", "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    setSubmitted(false);
    setDescription("");
    setMessage("");
    onClose();
  };

  return (
    <FormModal open={open} onClose={handleClose} title="Request Project Access" maxWidth="max-w-md">
      {submitted ? (
        <div className="flex flex-col items-center gap-4 py-6">
          <div className="w-12 h-12 rounded-full bg-success/20 flex items-center justify-center">
            <Icon name="check" size={24} className="text-success" />
          </div>
          <div className="text-center">
            <p className="text-sm font-medium text-text-primary mb-1">Request sent</p>
            <p className="text-xs text-text-secondary max-w-xs">
              We&apos;ll review your request and get back to you at{" "}
              <span className="font-medium">{email}</span>. In the meantime, you can join existing
              projects via invite or use the self-hosted version.
            </p>
          </div>
          <button
            onClick={handleClose}
            className="px-5 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-sm font-medium transition-colors"
          >
            Got it
          </button>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="rounded-lg bg-accent-muted/50 border border-accent/20 p-3">
            <p className="text-xs text-text-secondary leading-relaxed">
              Project creation is available to approved accounts. Fill out this form and
              we&apos;ll review your request. Alternatively, you can{" "}
              <strong>join existing projects</strong> via invite or use the{" "}
              <strong>self-hosted version</strong> to create your own.
            </p>
          </div>

          <div>
            <label className="block text-xs font-medium text-text-tertiary mb-1.5">
              Your email
            </label>
            <input
              className={inputCls}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
              maxLength={255}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-text-tertiary mb-1.5">
              Project description
            </label>
            <input
              className={inputCls}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="What kind of project do you want to create?"
              maxLength={500}
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-text-tertiary mb-1.5">
              Message
            </label>
            <textarea
              className={`${inputCls} min-h-[80px] resize-none`}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="Tell us a bit about your use case..."
              maxLength={2000}
            />
          </div>

          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            className="w-full px-5 py-2 rounded-lg bg-accent hover:bg-accent-hover text-white text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {submitting ? "Sending..." : "Send request"}
          </button>
        </div>
      )}
    </FormModal>
  );
}

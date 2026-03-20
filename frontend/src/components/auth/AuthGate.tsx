"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useAuthStore } from "@/stores/auth-store";
import { Icon } from "@/components/ui/Icon";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

function generateRandomToken(length = 32): string {
  const array = new Uint8Array(length);
  crypto.getRandomValues(array);
  return Array.from(array, (b) => b.toString(16).padStart(2, "0")).join("");
}

function setCookie(name: string, value: string) {
  document.cookie = `${name}=${value};path=/;SameSite=Strict;max-age=300`;
}

function getCookie(name: string): string | undefined {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${name}=`))
    ?.split("=")[1];
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, restore, login, register, googleLogin, isLoading, error } =
    useAuthStore();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [googleLoading, setGoogleLoading] = useState(false);
  const [restoring, setRestoring] = useState(true);
  const googleLoadingRef = useRef(false);
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const nonceRef = useRef<string>(generateRandomToken());

  useEffect(() => {
    restore();
    setRestoring(false);
  }, [restore]);

  const handleGoogleResponse = useCallback(
    async (response: { credential: string }) => {
      if (googleLoadingRef.current) return;
      googleLoadingRef.current = true;
      setGoogleLoading(true);
      try {
        const csrfToken = getCookie("g_csrf_token");
        await googleLogin(response.credential, nonceRef.current, csrfToken);
      } finally {
        nonceRef.current = generateRandomToken();
        googleLoadingRef.current = false;
        setGoogleLoading(false);
      }
    },
    [googleLogin],
  );

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || user) return;

    const csrfToken = generateRandomToken();
    setCookie("g_csrf_token", csrfToken);

    const initGoogle = () => {
      if (!window.google || !googleBtnRef.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleGoogleResponse,
        nonce: nonceRef.current,
      });
      window.google.accounts.id.renderButton(googleBtnRef.current, {
        theme: "filled_black",
        size: "large",
        width: "100%",
        text: "signin_with",
        shape: "pill",
      });
    };

    if (window.google) {
      initGoogle();
      return;
    }

    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = initGoogle;
    document.head.appendChild(script);

    return () => {
      script.remove();
    };
  }, [user, handleGoogleResponse]);

  if (restoring) {
    return (
      <div className="min-h-screen bg-surface-0 flex items-center justify-center">
        <p className="text-sm text-text-muted animate-pulse">Loading...</p>
      </div>
    );
  }

  if (user) return <>{children}</>;

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  const switchMode = (newMode: "login" | "register") => {
    setMode(newMode);
    useAuthStore.setState({ error: null });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!emailRegex.test(email)) {
      useAuthStore.setState({ error: "Please enter a valid email address" });
      return;
    }
    if (mode === "login") {
      await login(email, password);
    } else {
      await register(email, password, displayName);
    }
  };

  const inputCls =
    "w-full px-3.5 py-2.5 bg-surface-1 text-text-primary rounded-lg text-sm border border-border-subtle focus:border-accent focus:ring-1 focus:ring-accent focus:outline-none transition-colors placeholder-text-muted";

  return (
    <div className="min-h-screen bg-surface-0 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-accent to-blue-700 flex items-center justify-center mx-auto mb-4">
            <Icon name="zap" size={28} className="text-white" />
          </div>
          <h1 className="text-2xl font-bold text-text-primary tracking-tight">
            DB Agent
          </h1>
          <p className="text-sm text-text-tertiary mt-1">
            AI Database Query Assistant
          </p>
        </div>

        <form
          onSubmit={handleSubmit}
          className="bg-surface-1 rounded-xl p-6 space-y-4 border border-border-subtle"
        >
          <h2 className="text-lg font-semibold text-text-primary">
            {mode === "login" ? "Sign In" : "Create Account"}
          </h2>

          {mode === "register" && (
            <input
              type="text"
              placeholder="Display Name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className={inputCls}
              aria-label="Display Name"
            />
          )}

          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className={inputCls}
            aria-label="Email"
            aria-required="true"
          />

          <div>
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              className={inputCls}
              aria-label="Password"
              aria-required="true"
            />
            {mode === "register" && (
              <p className="text-[10px] text-text-muted mt-1 px-1">
                Min. 8 characters
              </p>
            )}
          </div>

          {error && (
            <p className="text-error text-xs flex items-center gap-1">
              <Icon name="x" size={12} />
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2.5 bg-accent text-white rounded-lg text-sm font-semibold hover:bg-accent-hover disabled:opacity-50 transition-colors"
          >
            {isLoading
              ? (mode === "login" ? "Signing in..." : "Creating account...")
              : mode === "login"
                ? "Sign In"
                : "Create Account"}
          </button>

          {GOOGLE_CLIENT_ID && (
            <>
              <div className="flex items-center gap-3">
                <div className="flex-1 border-t border-border-subtle" />
                <span className="text-[10px] text-text-muted uppercase tracking-wider">
                  or
                </span>
                <div className="flex-1 border-t border-border-subtle" />
              </div>
              <div
                ref={googleBtnRef}
                className={`flex justify-center ${googleLoading ? "opacity-50 pointer-events-none" : ""}`}
              />
              {googleLoading && (
                <p className="text-xs text-text-muted text-center animate-pulse">
                  Signing in with Google...
                </p>
              )}
            </>
          )}

          <p className="text-xs text-center text-text-tertiary">
            {mode === "login" ? (
              <>
                No account?{" "}
                <button
                  type="button"
                  onClick={() => switchMode("register")}
                  className="text-accent hover:text-accent-hover transition-colors"
                >
                  Register
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button
                  type="button"
                  onClick={() => switchMode("login")}
                  className="text-accent hover:text-accent-hover transition-colors"
                >
                  Sign In
                </button>
              </>
            )}
          </p>
        </form>

        <p className="text-center text-[11px] text-text-muted mt-4">
          <Link href="/terms" className="hover:text-text-tertiary transition-colors">
            Terms of Service
          </Link>
          <span className="mx-1.5">&middot;</span>
          <Link href="/privacy" className="hover:text-text-tertiary transition-colors">
            Privacy Policy
          </Link>
          <span className="mx-1.5">&middot;</span>
          <a href="mailto:contact@checkmydata.ai" className="hover:text-text-tertiary transition-colors">
            Contact
          </a>
        </p>
      </div>
    </div>
  );
}

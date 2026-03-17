"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAuthStore } from "@/stores/auth-store";

const GOOGLE_CLIENT_ID = process.env.NEXT_PUBLIC_GOOGLE_CLIENT_ID || "";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: Record<string, unknown>) => void;
          renderButton: (el: HTMLElement, config: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, restore, login, register, googleLogin, isLoading, error } = useAuthStore();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [googleLoading, setGoogleLoading] = useState(false);
  const googleLoadingRef = useRef(false);
  const googleBtnRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    restore();
  }, [restore]);

  const handleGoogleResponse = useCallback(
    async (response: { credential: string }) => {
      if (googleLoadingRef.current) return;
      googleLoadingRef.current = true;
      setGoogleLoading(true);
      try {
        await googleLogin(response.credential);
      } finally {
        googleLoadingRef.current = false;
        setGoogleLoading(false);
      }
    },
    [googleLogin],
  );

  useEffect(() => {
    if (!GOOGLE_CLIENT_ID || user) return;

    const initGoogle = () => {
      if (!window.google || !googleBtnRef.current) return;
      window.google.accounts.id.initialize({
        client_id: GOOGLE_CLIENT_ID,
        callback: handleGoogleResponse,
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
  }, [user, handleGoogleResponse]);

  if (user) return <>{children}</>;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (mode === "login") {
      await login(email, password);
    } else {
      await register(email, password, displayName);
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-4">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-bold text-zinc-100">DB Agent</h1>
          <p className="text-sm text-zinc-500 mt-1">AI Database Query Assistant</p>
        </div>

        <form onSubmit={handleSubmit} className="bg-zinc-900 rounded-xl p-6 space-y-4 border border-zinc-800">
          <h2 className="text-lg font-medium text-zinc-200">
            {mode === "login" ? "Sign In" : "Create Account"}
          </h2>

          {mode === "register" && (
            <input
              type="text"
              placeholder="Display Name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full px-3 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
            />
          )}

          <input
            type="email"
            placeholder="Email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            className="w-full px-3 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
          />

          <div>
            <input
              type="password"
              placeholder="Password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={6}
              className="w-full px-3 py-2 bg-zinc-800 text-zinc-200 rounded-lg text-sm border border-zinc-700 focus:border-zinc-500 focus:outline-none"
            />
            {mode === "register" && (
              <p className="text-[10px] text-zinc-500 mt-1 px-1">Min. 6 characters</p>
            )}
          </div>

          {error && <p className="text-red-400 text-xs">{error}</p>}

          <button
            type="submit"
            disabled={isLoading}
            className="w-full py-2 bg-zinc-200 text-zinc-900 rounded-lg text-sm font-medium hover:bg-zinc-300 disabled:opacity-50 transition-colors"
          >
            {isLoading ? "..." : mode === "login" ? "Sign In" : "Create Account"}
          </button>

          {GOOGLE_CLIENT_ID && (
            <>
              <div className="flex items-center gap-3">
                <div className="flex-1 border-t border-zinc-700" />
                <span className="text-[10px] text-zinc-500 uppercase tracking-wider">or</span>
                <div className="flex-1 border-t border-zinc-700" />
              </div>
              <div ref={googleBtnRef} className={`flex justify-center ${googleLoading ? "opacity-50 pointer-events-none" : ""}`} />
              {googleLoading && (
                <p className="text-xs text-zinc-500 text-center animate-pulse">Signing in with Google...</p>
              )}
            </>
          )}

          <p className="text-xs text-center text-zinc-500">
            {mode === "login" ? (
              <>
                No account?{" "}
                <button type="button" onClick={() => setMode("register")} className="text-zinc-300 hover:underline">
                  Register
                </button>
              </>
            ) : (
              <>
                Already have an account?{" "}
                <button type="button" onClick={() => setMode("login")} className="text-zinc-300 hover:underline">
                  Sign In
                </button>
              </>
            )}
          </p>
        </form>
      </div>
    </div>
  );
}

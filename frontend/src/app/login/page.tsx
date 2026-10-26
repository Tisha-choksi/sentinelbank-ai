"use client";

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthProvider";
import { ApiError } from "@/lib/api";

export default function LoginPage() {
  const { login, status } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      router.replace("/");
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "Could not sign in. Try again."
      );
    } finally {
      setSubmitting(false);
    }
  }

  // Covers navigating straight to /login while already signed in (e.g. the
  // back button) -- the post-submit redirect above handles the normal path.
  useEffect(() => {
    if (status === "authenticated") {
      router.replace("/");
    }
  }, [status, router]);

  return (
    <div className="flex min-h-screen w-full flex-col items-center justify-center bg-surface-page px-4">
      <div className="w-full max-w-sm rounded-xl border border-border bg-surface-card p-6">
        <div className="mb-6 flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-cat-1/15 text-cat-1">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden="true">
              <path
                d="M12 2 3 6v6c0 5 3.8 8.7 9 10 5.2-1.3 9-5 9-10V6l-9-4Z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
              />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold text-ink-primary">SentinelBank AI</p>
            <p className="text-xs text-ink-muted">Fraud investigation prototype</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="mb-1 block text-xs font-medium text-ink-secondary">
              Email
            </label>
            <input
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="analyst@sentinelbank.ai"
              className="w-full rounded-md border border-border bg-surface-page px-3 py-2 text-sm text-ink-primary placeholder:text-ink-muted focus:outline-none focus:ring-1 focus:ring-cat-1"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-ink-secondary">
              Password
            </label>
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full rounded-md border border-border bg-surface-page px-3 py-2 text-sm text-ink-primary placeholder:text-ink-muted focus:outline-none focus:ring-1 focus:ring-cat-1"
            />
          </div>

          {error && (
            <p className="text-xs" style={{ color: "var(--color-status-critical)" }}>
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-md bg-cat-1 px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <div className="mt-5 rounded-lg border border-border bg-surface-card-raised p-3 text-xs text-ink-muted">
          <p className="mb-1 font-medium text-ink-secondary">Demo accounts</p>
          <p>analyst@sentinelbank.ai / Analyst123!</p>
          <p>admin@sentinelbank.ai / Admin123!</p>
        </div>

        <p className="mt-4 text-center text-xs text-ink-muted">
          Synthetic banking data only. Not connected to a real financial
          institution.
        </p>
      </div>
    </div>
  );
}

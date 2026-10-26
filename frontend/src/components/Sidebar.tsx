"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/lib/AuthProvider";

const NAV_ITEMS = [
  { href: "/", label: "Overview" },
  { href: "/alerts", label: "Alert Queue" },
  { href: "/network", label: "Transaction Network" },
  { href: "/evaluation", label: "Model Evaluation" },
] as const;

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  return (
    <aside className="flex h-screen w-60 shrink-0 flex-col border-r border-border bg-surface-card">
      <div className="flex items-center gap-2 border-b border-border px-5 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-cat-1/15 text-cat-1">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path
              d="M12 2 3 6v6c0 5 3.8 8.7 9 10 5.2-1.3 9-5 9-10V6l-9-4Z"
              stroke="currentColor"
              strokeWidth="1.8"
              strokeLinejoin="round"
            />
          </svg>
        </div>
        <div>
          <div className="text-sm font-semibold text-ink-primary">SentinelBank AI</div>
          <div className="text-xs text-ink-muted">Fraud investigation prototype</div>
        </div>
      </div>

      <nav className="flex flex-1 flex-col gap-1 px-3 py-4">
        {NAV_ITEMS.map((item) => {
          const active =
            item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`rounded-md px-3 py-2 text-sm transition-colors ${
                active
                  ? "bg-cat-1/15 font-medium text-cat-1"
                  : "text-ink-secondary hover:bg-surface-hover hover:text-ink-primary"
              }`}
            >
              {item.label}
            </Link>
          );
        })}
      </nav>

      {user && (
        <div className="border-t border-border px-4 py-3">
          <p className="text-sm font-medium text-ink-primary">{user.full_name}</p>
          <p className="text-xs text-ink-muted">
            {user.email} &middot; {user.role}
          </p>
          <button
            onClick={handleLogout}
            className="mt-2 w-full rounded-md border border-border px-2 py-1 text-xs text-ink-secondary hover:bg-surface-hover"
          >
            Sign out
          </button>
        </div>
      )}

      <div className="border-t border-border px-4 py-4 text-xs text-ink-muted">
        <p className="font-medium text-ink-secondary">Prototype notice</p>
        <p className="mt-1">
          Synthetic banking data only. Not connected to a real financial
          institution.
        </p>
      </div>
    </aside>
  );
}

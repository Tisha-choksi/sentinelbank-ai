"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/AuthProvider";
import { Sidebar } from "./Sidebar";

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { status } = useAuth();
  const isLoginPage = pathname === "/login";

  useEffect(() => {
    if (!isLoginPage && status === "unauthenticated") {
      router.replace("/login");
    }
  }, [isLoginPage, status, router]);

  if (isLoginPage) {
    return <>{children}</>;
  }

  if (status === "loading") {
    return (
      <div className="flex min-h-screen flex-1 items-center justify-center text-sm text-ink-muted">
        Loading...
      </div>
    );
  }

  if (status === "unauthenticated") {
    // Redirect effect above is in flight; render nothing rather than a
    // flash of protected content.
    return null;
  }

  return (
    <div className="flex min-h-screen flex-1">
      <Sidebar />
      <div className="flex min-h-screen flex-1 flex-col overflow-x-hidden">
        {children}
      </div>
    </div>
  );
}

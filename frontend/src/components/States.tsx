export function LoadingState({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-12 text-sm text-ink-muted">
      <span
        aria-hidden="true"
        className="h-3 w-3 animate-pulse rounded-full bg-cat-1"
      />
      {label}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div
      className="flex items-start gap-3 rounded-lg border px-4 py-3 text-sm"
      style={{
        borderColor: "var(--color-status-critical)",
        backgroundColor: "color-mix(in srgb, var(--color-status-critical) 10%, transparent)",
      }}
      role="alert"
    >
      <span
        aria-hidden="true"
        className="mt-0.5"
        style={{ color: "var(--color-status-critical)" }}
      >
        ■
      </span>
      <div className="flex-1">
        <p className="font-medium text-ink-primary">Couldn&apos;t load this data</p>
        <p className="mt-0.5 text-ink-secondary">{message}</p>
      </div>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 rounded-md border border-border px-3 py-1 text-xs font-medium text-ink-primary hover:bg-surface-hover"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-border py-14 text-center">
      <p className="text-sm font-medium text-ink-primary">{title}</p>
      {description && (
        <p className="max-w-sm text-sm text-ink-muted">{description}</p>
      )}
    </div>
  );
}

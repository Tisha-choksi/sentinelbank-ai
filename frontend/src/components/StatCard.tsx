export function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string | number;
  accent?: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface-card px-5 py-4">
      <p className="text-sm text-ink-muted">{label}</p>
      <p
        className="mt-1.5 text-3xl font-semibold text-ink-primary"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </p>
    </div>
  );
}

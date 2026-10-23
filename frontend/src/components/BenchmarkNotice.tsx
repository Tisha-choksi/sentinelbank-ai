export function BenchmarkNotice() {
  return (
    <div
      className="flex items-start gap-3 rounded-lg border px-4 py-3 text-sm"
      style={{
        borderColor: "var(--color-status-warning)",
        backgroundColor:
          "color-mix(in srgb, var(--color-status-warning) 8%, transparent)",
      }}
    >
      <span
        aria-hidden="true"
        className="mt-0.5"
        style={{ color: "var(--color-status-warning)" }}
      >
        ▲
      </span>
      <p className="text-ink-secondary">
        <span className="font-medium text-ink-primary">
          Offline benchmark results, not live telemetry.
        </span>{" "}
        Every number on this page comes from a one-time evaluation run (30
        sampled scenarios per quality category, fixed temperature, saved to
        disk) -- not continuous production monitoring. Latency, timeout, and
        reliability figures describe that benchmark run, not the current
        health of this service.
      </p>
    </div>
  );
}

export function fmtPct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return `${(value * 100).toFixed(1)}%`;
}

export function fmtSeconds(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return `${value.toFixed(1)}s`;
}

export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "n/a";
  return new Date(value).toLocaleString();
}

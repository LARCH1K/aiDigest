export function formatDate(value: string | null): string | undefined {
  const date = value?.match(/^(\d{4}-\d{2}-\d{2})(?:$|T)/)?.[1];
  if (!date) return;
  const parsed = new Date(date);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== date) return;
  return date.split("-").reverse().join(".");
}

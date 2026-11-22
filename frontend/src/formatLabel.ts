export function formatLabel(value: string): string {
  return value.replace(/^\p{L}/u, (letter) => letter.toLocaleUpperCase("ru"));
}

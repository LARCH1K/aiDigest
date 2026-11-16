export function safeUrl(url: string | null | undefined): string {
  if (!url || !/^https?:\/\//i.test(url)) return "#";
  try {
    return new URL(url).hostname ? url : "#";
  } catch {
    return "#";
  }
}

export function safeNext(next: string | null): string {
  if (!next || /[\x00-\x1f\x7f]/.test(next)) return "/";

  let path = next.split(/[?#]/, 1)[0];
  while (path.startsWith("/") && !path.startsWith("//") && !/[\\\x00-\x1f\x7f]/.test(path)) {
    // Проверяем и форму после нормализации сегментов "." и "..".
    if (new URL(path, "https://aidigest.invalid").pathname.startsWith("//")) return "/";

    // Раскрываем вложенное кодирование только для разделителей, точек и управляющих символов.
    const decoded = path.replace(/%(25|2f|5c|2e|0[0-9a-f]|1[0-9a-f]|7f)/gi,
      (_, hex: string) => String.fromCharCode(parseInt(hex, 16)));
    if (decoded === path) return next;
    path = decoded;
  }
  return "/";
}

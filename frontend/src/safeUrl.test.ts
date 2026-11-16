import { expect, it } from "vitest";
import { safeNext, safeUrl } from "./safeUrl";

it.each(["javascript:alert(1)", "//ai.gov.ru/x", "https://", "/case/a", "", null, undefined])(
  "не создаёт ссылку из %s",
  (url) => expect(safeUrl(url)).toBe("#"),
);

it.each(["https://ai.gov.ru/x", "http://example.test/новость?q=1"])(
  "сохраняет адрес источника %s",
  (url) => expect(safeUrl(url)).toBe(url),
);

it.each([
  "//evil.test", "https://evil.test", "/\\evil.test", "/%5Cevil.test",
  "/%2Fevil.test", "/%252Fevil.test", "/%09/evil.test", "/.//evil.test",
  "/a/..//evil.test", "/%2e%2e//evil.test", "/\t/evil.test",
])("отклоняет небезопасный next %s", (next) => {
  expect(safeNext(next)).toBe("/");
});

it.each(["/case/1?level=%D0%A0#metrics", "/?q=https%3A%2F%2Fexample.test", "/case/100%25"])(
  "сохраняет внутренний путь %s",
  (next) => expect(safeNext(next)).toBe(next),
);

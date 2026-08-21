import "@testing-library/jest-dom/vitest";

// Node 25+ экспортирует собственный localStorage, который затеняет jsdom и без
// --localstorage-file неработоспособен ("setItem is not a function").
// Подменяем полноценной реализацией поверх Map.
const store = new Map<string, string>();

Object.defineProperty(globalThis, "localStorage", {
  configurable: true,
  value: {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, String(value)),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
  },
});

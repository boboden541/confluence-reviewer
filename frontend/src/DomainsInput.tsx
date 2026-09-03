import { useState } from "react";

/** Ввод доменов-тегов: чипы с крестиком + свободное поле (Enter или кнопка).
 *  Дубликаты без учёта регистра не добавляются — как на backend. */
export function DomainsInput({
  domains,
  onChange,
  addLabel = "＋ добавить домен",
}: {
  domains: string[];
  onChange: (next: string[]) => void;
  addLabel?: string;
}) {
  const [draft, setDraft] = useState("");

  const add = () => {
    const value = draft.trim();
    if (!value) return;
    if (domains.some((d) => d.toLowerCase() === value.toLowerCase())) {
      setDraft("");
      return;
    }
    onChange([...domains, value]);
    setDraft("");
  };

  const remove = (index: number) => {
    onChange(domains.filter((_, i) => i !== index));
  };

  return (
    <div className="dom-edit">
      {domains.map((domain, index) => (
        <span key={domain.toLowerCase()} className="domain-chip">
          {domain}{" "}
          <button
            type="button"
            className="chip-x"
            aria-label={`Убрать домен ${domain}`}
            onClick={() => remove(index)}
          >
            ×
          </button>
        </span>
      ))}
      <span className="dom-add-row">
        <input
          className="dom-input"
          type="text"
          placeholder="Новый домен"
          aria-label="Новый домен"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <button type="button" className="dom-add" onClick={add}>
          {addLabel}
        </button>
      </span>
    </div>
  );
}

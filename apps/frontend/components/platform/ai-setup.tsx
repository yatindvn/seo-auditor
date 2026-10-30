"use client";

import { useState } from "react";
import { X } from "lucide-react";
import type { AiBrands, AiPrompt } from "@seo-auditor/shared";

import { ApiError, Platform } from "@/services/platform";

function TermsRow({ owner, terms, onSave }: { owner: string; terms: string[]; onSave: (terms: string[]) => Promise<void> }) {
  const [value, setValue] = useState("");
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="min-w-[140px] text-sm font-medium">{owner}</span>
      {terms.map((t) => (
        <span key={t} className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs">{t}
          <button type="button" aria-label={`Remove ${t}`} onClick={() => onSave(terms.filter((x) => x !== t))}><X className="h-3 w-3" aria-hidden /></button></span>
      ))}
      <input aria-label={`Alias for ${owner}`} value={value} maxLength={100} onChange={(e) => setValue(e.target.value)}
             className="h-8 w-40 rounded-full border bg-background px-3 text-xs" placeholder="Add a name…" />
      <button type="button" aria-label={`Add alias for ${owner}`} disabled={!value.trim()}
              onClick={async () => { await onSave([...terms, value.trim()]); setValue(""); }}
              className="h-8 rounded-full border px-3 text-xs active:scale-95 disabled:opacity-50">Add</button>
    </div>
  );
}

export function BrandTerms({ projectId, brands, onChanged }: { projectId: number; brands: AiBrands; onChanged: () => void }) {
  const [error, setError] = useState<string | null>(null);
  const save = async (body: { self?: string[]; competitors?: Record<string, string[]> }) => {
    setError(null);
    try { await Platform.saveAiBrands(projectId, body); onChanged(); }
    catch (e) { setError(e instanceof ApiError ? e.detail : "Could not save"); }
  };
  return (
    <section className="min-w-0 space-y-3 rounded-[18px] border bg-card p-5">
      <h2 className="font-semibold tracking-tight">Brand names</h2>
      <p className="text-xs text-muted-foreground">Matched as whole words, case-insensitive. Domains always count.</p>
      <TermsRow owner={brands.self.domain} terms={brands.self.terms} onSave={(terms) => save({ self: terms })} />
      {brands.competitors.map((c) => (
        <TermsRow key={c.domain} owner={c.domain} terms={c.terms} onSave={(terms) => save({ competitors: { [c.domain]: terms } })} />
      ))}
      {brands.competitors.length === 0 && <p className="text-xs text-muted-foreground">Add competitors in the Rank Tracker tab to compare against them.</p>}
      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">{error}</p>}
    </section>
  );
}

export function Prompts({ projectId, prompts, onChanged }: { projectId: number; prompts: AiPrompt[]; onChanged: () => void }) {
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try { await fn(); onChanged(); } catch (e) { setError(e instanceof ApiError ? e.detail : "Something went wrong"); }
  };
  return (
    <section className="min-w-0 space-y-3 rounded-[18px] border bg-card p-5">
      <h2 className="font-semibold tracking-tight">Prompts <span className="text-xs font-normal text-muted-foreground">({prompts.length}/25)</span></h2>
      <ul className="divide-y text-sm">
        {prompts.map((p) => (
          <li key={p.id} className="flex items-center gap-3 py-2">
            <input type="checkbox" aria-label={`Enable ${p.text}`} checked={p.enabled}
                   onChange={(e) => act(() => Platform.updateAiPrompt(p.id, { enabled: e.target.checked }))} />
            <span className={`min-w-0 flex-1 break-words ${p.enabled ? "" : "text-muted-foreground line-through"}`}>{p.text}</span>
            <button type="button" aria-label={`Delete ${p.text}`} onClick={() => act(() => Platform.deleteAiPrompt(p.id))}
                    className="rounded-full border px-2 py-0.5 text-xs active:scale-95">Delete</button>
          </li>
        ))}
      </ul>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); act(async () => { await Platform.addAiPrompt(projectId, text.trim()); setText(""); }); }}>
        <input aria-label="New prompt" value={text} maxLength={300} onChange={(e) => setText(e.target.value)}
               placeholder="e.g. best online bookstore for rare books" className="h-9 min-w-0 flex-1 rounded-full border bg-background px-3 text-sm" />
        <button type="submit" disabled={!text.trim() || prompts.length >= 25} aria-label="Add prompt"
                className="h-9 rounded-full border px-4 text-sm active:scale-95 disabled:opacity-50">Add</button>
      </form>
      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">{error}</p>}
    </section>
  );
}

"use client";

import { useState } from "react";
import type { CustomRule, RuleSeverity, RuleTestResult } from "@seo-auditor/shared";

import { buildRule, CHECK_TYPES, emptyForm, FIELD_OPTIONS, formFromRule, isNumeric, needsValue, opsFor, type RuleForm as Form } from "@/lib/rules";
import { ApiError, Platform } from "@/services/platform";

const input = "h-9 w-full rounded-lg border bg-background px-3 text-sm";
const label = "space-y-1 text-xs font-medium text-muted-foreground";

export function RuleForm({ projectId, initial, onSaved, onCancel }: {
  projectId: number; initial?: CustomRule; onSaved: (rule: CustomRule) => void; onCancel: () => void;
}) {
  const [form, setForm] = useState<Form>(initial ? formFromRule(initial) : emptyForm());
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [testUrl, setTestUrl] = useState("");
  const [test, setTest] = useState<RuleTestResult | null>(null);
  const [testError, setTestError] = useState<string | null>(null);
  const ops = opsFor(form);

  const set = (patch: Partial<Form>) => {
    setForm((f) => {
      const next = { ...f, ...patch };
      if (!opsFor(next).some((o) => o.value === next.op)) next.op = opsFor(next)[0].value;
      return next;
    });
    setTest(null);
  };

  const save = async () => {
    setSaving(true); setError(null);
    try {
      const rule = buildRule(form);
      onSaved(initial ? await Platform.updateRule(initial.id, rule) : await Platform.createRule(projectId, rule));
    } catch (e) {
      setError(e instanceof ApiError ? e.detail : "Could not save the rule");
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTestError(null); setTest(null);
    try {
      setTest(await Platform.testRule(projectId, testUrl.trim(), buildRule(form)));
    } catch (e) {
      setTestError(e instanceof ApiError ? e.detail : "Test failed");
    }
  };

  return (
    <form className="space-y-4 rounded-[18px] border bg-card p-5" onSubmit={(e) => { e.preventDefault(); save(); }}>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={label}>Name<input aria-label="Name" className={input} value={form.name} maxLength={80} onChange={(e) => set({ name: e.target.value })} /></label>
        <label className={label}>Severity
          <select aria-label="Severity" className={input} value={form.severity} onChange={(e) => set({ severity: e.target.value as RuleSeverity })}>
            <option value="critical">Critical</option><option value="warning">Warning</option><option value="info">Info</option>
          </select>
        </label>
      </div>
      <div className="grid gap-3 sm:grid-cols-4">
        <label className={label}>Check
          <select aria-label="Check" className={input} value={form.type} onChange={(e) => set({ type: e.target.value as Form["type"] })}>
            {CHECK_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </label>
        {form.type === "field" && (
          <label className={label}>Field
            <select aria-label="Field" className={input} value={form.field} onChange={(e) => set({ field: e.target.value })}>
              {FIELD_OPTIONS.map((f) => <option key={f.value} value={f.value}>{f.label}</option>)}
            </select>
          </label>
        )}
        {form.type === "text" && (
          <label className={label}>Look in
            <select aria-label="Look in" className={input} value={form.scope} onChange={(e) => set({ scope: e.target.value as "visible" | "html" })}>
              <option value="visible">Visible text</option><option value="html">Raw HTML</option>
            </select>
          </label>
        )}
        {form.type === "selector" && (
          <label className={label}>CSS selector<input aria-label="CSS selector" className={`${input} font-mono`} value={form.selector} maxLength={200} onChange={(e) => set({ selector: e.target.value })} /></label>
        )}
        <label className={label}>Condition
          <select aria-label="Condition" className={input} value={form.op} onChange={(e) => set({ op: e.target.value })}>
            {ops.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </label>
        {needsValue(form.op) && (
          <label className={label}>Value
            <input aria-label="Value" className={input} type={isNumeric(form.op) ? "number" : "text"} min={0} maxLength={200}
                   value={form.value} onChange={(e) => set({ value: e.target.value })} />
          </label>
        )}
      </div>
      {form.type === "text" && (
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={form.caseSensitive} onChange={(e) => set({ caseSensitive: e.target.checked })} />Case-sensitive</label>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className={label}>Only on URLs matching (optional)<input aria-label="URL pattern" className={`${input} font-mono`} placeholder="/blog/*" value={form.urlPattern} onChange={(e) => set({ urlPattern: e.target.value })} /></label>
        <label className={label}>Message (optional)<input aria-label="Message" className={input} maxLength={200} value={form.message} onChange={(e) => set({ message: e.target.value })} /></label>
      </div>

      <div className="space-y-2 rounded-xl border border-dashed p-3">
        <div className="flex flex-wrap items-end gap-2">
          <label className={`${label} min-w-0 flex-1`}>Test on a URL<input aria-label="Test on a URL" className={input} placeholder="https://…" value={testUrl} onChange={(e) => setTestUrl(e.target.value)} /></label>
          <button type="button" onClick={runTest} disabled={!testUrl.trim()} className="h-9 rounded-full border px-4 text-sm active:scale-95 disabled:opacity-50">Test</button>
        </div>
        {testError && <p className="text-sm text-rose-700 dark:text-rose-400">{testError}</p>}
        {test && (
          <p className="text-sm">
            {!test.applies ? "Doesn't apply to this URL (outside the URL pattern)."
              : <>{test.passed ? <span className="font-medium text-emerald-700 dark:text-emerald-400">Passed</span>
                               : <span className="font-medium text-rose-700 dark:text-rose-400">Failed</span>}
                 <span className="text-muted-foreground"> · saw: {String(test.observed)}</span></>}
          </p>
        )}
      </div>

      {error && <p role="alert" className="text-sm text-rose-700 dark:text-rose-400">{error}</p>}
      <div className="flex gap-2">
        <button type="submit" disabled={saving || !form.name.trim()} className="rounded-full bg-primary px-4 py-2 text-sm font-medium text-primary-foreground active:scale-95 disabled:opacity-50">Save rule</button>
        <button type="button" onClick={onCancel} className="rounded-full border px-4 py-2 text-sm active:scale-95">Cancel</button>
      </div>
    </form>
  );
}

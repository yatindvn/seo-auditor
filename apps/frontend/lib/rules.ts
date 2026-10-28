import type { CustomRule, NewRule, RuleCheck, RuleSeverity } from "@seo-auditor/shared";

export type CheckType = "field" | "text" | "selector";
export interface RuleForm {
  name: string; severity: RuleSeverity; message: string; urlPattern: string;
  type: CheckType; field: string; scope: "visible" | "html"; selector: string;
  op: string; value: string; caseSensitive: boolean;
}

export const CHECK_TYPES: { value: CheckType; label: string }[] = [
  { value: "field", label: "Page field" }, { value: "text", label: "Page text" }, { value: "selector", label: "CSS selector" },
];

const TEXT_FIELDS = ["title", "meta_description", "h1", "canonical", "meta_robots"];
export const FIELD_OPTIONS = [
  { value: "title", label: "Title" }, { value: "meta_description", label: "Meta description" }, { value: "h1", label: "H1" },
  { value: "canonical", label: "Canonical" }, { value: "meta_robots", label: "Meta robots" },
  { value: "word_count", label: "Word count" }, { value: "internal_links_count", label: "Internal links" },
  { value: "external_links_count", label: "External links" }, { value: "status", label: "Status code" },
  { value: "response_time_ms", label: "Response time (ms)" },
];

const TEXT_OPS = [
  { value: "contains", label: "contains" }, { value: "not_contains", label: "doesn't contain" },
  { value: "equals", label: "is exactly" }, { value: "not_equals", label: "is not" },
  { value: "starts_with", label: "starts with" }, { value: "ends_with", label: "ends with" },
  { value: "is_empty", label: "is empty" }, { value: "is_not_empty", label: "is not empty" },
  { value: "length_gte", label: "length at least" }, { value: "length_lte", label: "length at most" },
];
const NUMBER_OPS = [{ value: "gte", label: "at least" }, { value: "lte", label: "at most" }, { value: "eq", label: "exactly" }];
const SELECTOR_OPS = [
  { value: "exists", label: "exists" }, { value: "not_exists", label: "doesn't exist" },
  { value: "count_eq", label: "appears exactly" }, { value: "count_gte", label: "appears at least" },
  { value: "count_lte", label: "appears at most" },
];
const TEXT_CHECK_OPS = [{ value: "contains", label: "contains" }, { value: "not_contains", label: "doesn't contain" }];
const VALUELESS = new Set(["is_empty", "is_not_empty", "exists", "not_exists"]);
const NUMERIC = new Set(["gte", "lte", "eq", "length_gte", "length_lte", "count_eq", "count_gte", "count_lte"]);

export function opsFor(form: Pick<RuleForm, "type" | "field">) {
  if (form.type === "text") return TEXT_CHECK_OPS;
  if (form.type === "selector") return SELECTOR_OPS;
  return TEXT_FIELDS.includes(form.field) ? TEXT_OPS : NUMBER_OPS;
}

export const needsValue = (op: string) => !VALUELESS.has(op);
export const isNumeric = (op: string) => NUMERIC.has(op);

export function emptyForm(): RuleForm {
  return { name: "", severity: "warning", message: "", urlPattern: "", type: "field", field: "title",
           scope: "visible", selector: "", op: "contains", value: "", caseSensitive: false };
}

export function formFromRule(rule: CustomRule): RuleForm {
  const c = rule.check as any;
  return { ...emptyForm(), name: rule.name, severity: rule.severity, message: rule.message ?? "",
           urlPattern: rule.url_pattern ?? "", type: c.type, field: c.field ?? "title", scope: c.scope ?? "visible",
           selector: c.selector ?? "", op: c.op, value: c.value == null ? "" : String(c.value), caseSensitive: !!c.case_sensitive };
}

export function buildRule(form: RuleForm): NewRule {
  const value = needsValue(form.op) ? (isNumeric(form.op) ? Number(form.value) : form.value) : undefined;
  let check: RuleCheck;
  if (form.type === "text") {
    check = { type: "text", scope: form.scope, op: form.op as "contains" | "not_contains", value: form.value,
              ...(form.caseSensitive ? { case_sensitive: true } : {}) };
  } else if (form.type === "selector") {
    check = { type: "selector", selector: form.selector, op: form.op, ...(value !== undefined ? { value: value as number } : {}) };
  } else {
    check = { type: "field", field: form.field, op: form.op, ...(value !== undefined ? { value } : {}) };
  }
  return { name: form.name.trim(), severity: form.severity, message: form.message.trim(),
           url_pattern: form.urlPattern.trim() || null, check };
}

export const EXAMPLE_RULE: NewRule = {
  name: "Every page has a title", severity: "warning", message: "Add a unique <title>.", url_pattern: null,
  check: { type: "field", field: "title", op: "is_not_empty" },
};

export function isValidUrl(url) {
    if (!url || typeof url !== "string")
        return false;
    try {
        const formatted = url.startsWith("http://") || url.startsWith("https://") ? url : `https://${url}`;
        const parsed = new URL(formatted);
        return Boolean(parsed.hostname);
    }
    catch {
        return false;
    }
}
export function sanitizeUrl(url) {
    const trimmed = (url || "").trim();
    if (!trimmed)
        return "";
    if (!trimmed.startsWith("http://") && !trimmed.startsWith("https://")) {
        return `https://${trimmed}`;
    }
    return trimmed;
}

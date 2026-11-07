export function imageMimeType(base64?: string, url?: string): string {
  if (/\.svg(?:$|[?#])/i.test(url || "")) return "image/svg+xml";
  if (base64) {
    try { if (/^(?:\uFEFF)?\s*(?:<\?xml[^>]*>\s*)?(?:<!--[\s\S]*?-->\s*)*<svg[\s>]/i.test(atob(base64.slice(0, 1024)))) return "image/svg+xml"; } catch { /* Other formats use magic prefixes below. */ }
  }
  if (base64?.startsWith("R0lG") || /\.gif(?:$|[?#])/i.test(url || "")) return "image/gif";
  if (base64?.startsWith("/9j/") || /\.jpe?g(?:$|[?#])/i.test(url || "")) return "image/jpeg";
  if (base64?.startsWith("UklGR") || /\.webp(?:$|[?#])/i.test(url || "")) return "image/webp";
  return "image/png";
}

export function imageFileExtension(mime: string): string {
  return ({ "image/svg+xml": "svg", "image/gif": "gif", "image/jpeg": "jpg", "image/webp": "webp" } as Record<string, string>)[mime] || "png";
}

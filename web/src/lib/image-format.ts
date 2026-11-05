export function imageMimeType(base64?: string, url?: string): string {
  if (base64?.startsWith("R0lG") || /\.gif(?:$|[?#])/i.test(url || "")) return "image/gif";
  if (base64?.startsWith("/9j/") || /\.jpe?g(?:$|[?#])/i.test(url || "")) return "image/jpeg";
  if (base64?.startsWith("UklGR") || /\.webp(?:$|[?#])/i.test(url || "")) return "image/webp";
  return "image/png";
}

export function imageFileExtension(mime: string): string {
  return ({ "image/gif": "gif", "image/jpeg": "jpg", "image/webp": "webp" } as Record<string, string>)[mime] || "png";
}

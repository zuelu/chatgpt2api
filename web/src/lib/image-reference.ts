"use client";

// Check encoded headers rather than names: product images may have a .jpg name
// while actually containing GIF, animated WebP, or APNG data.
async function needsStillFrame(file: File): Promise<boolean> {
  const bytes = new Uint8Array(await file.slice(0, 65536).arrayBuffer());
  const text = (offset: number, length: number) => String.fromCharCode(...bytes.slice(offset, offset + length));
  if (text(0, 6) === "GIF87a" || text(0, 6) === "GIF89a") return true;
  if (text(0, 4) === "RIFF" && text(8, 4) === "WEBP") {
    return text(12, 4) === "VP8X" && Boolean(bytes[20] & 2);
  }
  if (bytes[0] === 137 && text(1, 3) === "PNG") {
    const view = new DataView(bytes.buffer);
    for (let offset = 8; offset + 12 <= bytes.length;) {
      const kind = text(offset + 4, 4);
      if (kind === "acTL") return true;
      if (kind === "IDAT" || kind === "IEND") break;
      offset += view.getUint32(offset) + 12;
    }
  }
  return false;
}

export async function prepareReferenceFile(file: File, errorMessage: string): Promise<{ file: File; firstFrame: boolean }> {
  if (!await needsStillFrame(file)) return { file, firstFrame: false };
  let bitmap: ImageBitmap | null = null;
  try {
    // ImageBitmap captures the default/first frame; it never starts playback.
    bitmap = await createImageBitmap(file);
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext("2d");
    if (!context) throw new Error(errorMessage);
    context.drawImage(bitmap, 0, 0);
    const blob = await new Promise<Blob>((resolve, reject) => canvas.toBlob(
      (result) => result ? resolve(result) : reject(new Error(errorMessage)), "image/png",
    ));
    const name = file.name.replace(/\.[^.]+$/, "") || "reference";
    return { file: new File([blob], `${name}.png`, { type: "image/png" }), firstFrame: true };
  } catch {
    throw new Error(errorMessage);
  } finally {
    bitmap?.close();
  }
}

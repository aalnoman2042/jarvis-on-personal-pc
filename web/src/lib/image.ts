/* Making a photo small enough to send.
 *
 * A modern phone camera produces several megabytes of detail no vision model
 * uses. Uploading that whole is what makes "show Jarvis something" feel broken
 * on mobile data — the answer is fine, the wait is not.
 *
 * Shared by the Vision panel and the chat composer. It lived in the panel first
 * and was about to be copied into the composer, which is how two subtly
 * different shrinkers end up in one app and only one of them handles HEIC.
 */

/** Beyond this a vision model gains nothing and the upload costs real seconds. */
const MAX_DIM = 1600;
const QUALITY = 0.85;

export async function shrink(file: Blob): Promise<Blob> {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_DIM / Math.max(bitmap.width, bitmap.height));
    const w = Math.round(bitmap.width * scale);
    const h = Math.round(bitmap.height * scale);
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return file;
    ctx.drawImage(bitmap, 0, 0, w, h);
    // Freeing the bitmap matters on a phone: several of these in a
    // conversation is real memory, and the GC will not hurry.
    bitmap.close?.();
    return await new Promise((resolve) =>
      canvas.toBlob((b) => resolve(b || file), "image/jpeg", QUALITY),
    );
  } catch {
    // A format the canvas cannot decode — HEIC on some browsers — still
    // uploads as it is. The server handles the un-shrunk case.
    return file;
  }
}

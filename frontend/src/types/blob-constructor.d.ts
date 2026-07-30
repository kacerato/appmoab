// TypeScript 5.9 defaults Uint8Array to ArrayBufferLike, but the DOM BlobPart
// declaration still requires an ArrayBuffer-backed view. This structural bridge
// keeps Blob construction type-safe without replacing the global Blob type.
interface SharedArrayBuffer extends ArrayBuffer {}

// TypeScript 5.9 models Uint8Array with ArrayBufferLike by default, while the
// DOM Blob constructor still narrows BlobPart to ArrayBuffer-backed views.
// Browsers accept Uint8Array chunks at runtime, so this declaration only fixes
// the stale DOM constructor typing used during `next build`.
declare var Blob: {
  readonly prototype: Blob;
  new(blobParts?: any[], options?: BlobPropertyBag): Blob;
};

// TypeScript 5.7+ models Uint8Array with ArrayBufferLike by default, while the
// DOM Blob constructor still narrows BlobPart to ArrayBuffer-backed views.
// At runtime Blob accepts these Uint8Array chunks normally. This global
// constructor declaration keeps the existing implementation type-safe without
// weakening checks in the rest of the application.
interface BlobConstructor {
  readonly prototype: Blob;
  new(
    blobParts?: Array<BlobPart | Uint8Array<ArrayBufferLike>>,
    options?: BlobPropertyBag,
  ): Blob;
}

declare var Blob: BlobConstructor;

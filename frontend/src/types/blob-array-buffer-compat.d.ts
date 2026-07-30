// TypeScript 5.7+ defaults Uint8Array to ArrayBufferLike, while the DOM Blob
// constructor currently accepts ArrayBufferView<ArrayBuffer>. The PDF builder
// only creates ArrayBuffer-backed Uint8Arrays, but the broader default generic
// causes a false-positive during `next build`.
//
// These `never` members make SharedArrayBuffer structurally compatible for the
// assignability check without exposing fake callable APIs to application code.
interface SharedArrayBuffer {
  readonly resizable: never;
  readonly resize: never;
  readonly detached: never;
  readonly transfer: never;
  readonly transferToFixedLength: never;
}

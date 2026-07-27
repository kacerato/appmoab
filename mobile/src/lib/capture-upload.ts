type CaptureUploadListener = (activeHydrometerIds: ReadonlySet<string>) => void;

const activeUploads = new Set<string>();
const listeners = new Set<CaptureUploadListener>();

function notifyListeners() {
  const snapshot = new Set(activeUploads);
  listeners.forEach(listener => listener(snapshot));
}

export function getActiveCaptureUploads(): ReadonlySet<string> {
  return new Set(activeUploads);
}

export function subscribeCaptureUploads(listener: CaptureUploadListener) {
  listeners.add(listener);
  listener(getActiveCaptureUploads());
  return () => {
    listeners.delete(listener);
  };
}

export function enqueueCaptureUpload(
  hydrometerId: string,
  operation: () => Promise<void>,
): boolean {
  if (activeUploads.has(hydrometerId)) return false;

  activeUploads.add(hydrometerId);
  notifyListeners();

  void Promise.resolve()
    .then(operation)
    .finally(() => {
      activeUploads.delete(hydrometerId);
      notifyListeners();
    });

  return true;
}

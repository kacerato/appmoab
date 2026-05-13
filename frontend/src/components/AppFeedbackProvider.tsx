'use client';

import { createContext, ReactNode, useCallback, useContext, useMemo, useRef, useState } from 'react';
import { CheckCircle2, CircleAlert, Info, TriangleAlert } from 'lucide-react';

type ToastTone = 'success' | 'error' | 'warning' | 'info';
type DialogMode = 'confirm' | 'prompt';

interface ToastItem {
  id: number;
  title: string;
  description?: string;
  tone: ToastTone;
}

interface DialogState {
  mode: DialogMode;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  defaultValue?: string;
  placeholder?: string;
}

interface FeedbackContextValue {
  notify: (title: string, description?: string, tone?: ToastTone) => void;
  confirm: (title: string, description?: string, options?: { confirmLabel?: string; cancelLabel?: string }) => Promise<boolean>;
  prompt: (
    title: string,
    description?: string,
    options?: { confirmLabel?: string; cancelLabel?: string; defaultValue?: string; placeholder?: string }
  ) => Promise<string | null>;
}

const FeedbackContext = createContext<FeedbackContextValue | null>(null);

export function AppFeedbackProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);
  const [dialog, setDialog] = useState<DialogState | null>(null);
  const [promptValue, setPromptValue] = useState('');
  const resolverRef = useRef<((value: boolean | string | null) => void) | null>(null);
  const nextIdRef = useRef(1);

  const notify = useCallback((title: string, description?: string, tone: ToastTone = 'info') => {
    const id = nextIdRef.current++;
    setToasts(current => [...current, { id, title, description, tone }]);
    window.setTimeout(() => {
      setToasts(current => current.filter(item => item.id !== id));
    }, 3800);
  }, []);

  const confirm = useCallback((title: string, description?: string, options?: { confirmLabel?: string; cancelLabel?: string }) => {
    return new Promise<boolean>((resolve) => {
      resolverRef.current = (value) => resolve(value === true);
      setDialog({
        mode: 'confirm',
        title,
        description,
        confirmLabel: options?.confirmLabel,
        cancelLabel: options?.cancelLabel,
      });
    });
  }, []);

  const prompt = useCallback((
    title: string,
    description?: string,
    options?: { confirmLabel?: string; cancelLabel?: string; defaultValue?: string; placeholder?: string }
  ) => {
    return new Promise<string | null>((resolve) => {
      resolverRef.current = (value) => resolve(typeof value === 'string' ? value : null);
      setPromptValue(options?.defaultValue || '');
      setDialog({
        mode: 'prompt',
        title,
        description,
        confirmLabel: options?.confirmLabel,
        cancelLabel: options?.cancelLabel,
        defaultValue: options?.defaultValue,
        placeholder: options?.placeholder,
      });
    });
  }, []);

  const closeDialog = useCallback((value: boolean | string | null) => {
    const resolver = resolverRef.current;
    resolverRef.current = null;
    setDialog(null);
    setPromptValue('');
    resolver?.(value);
  }, []);

  const value = useMemo(() => ({ notify, confirm, prompt }), [notify, confirm, prompt]);

  return (
    <FeedbackContext.Provider value={value}>
      {children}

      <div className="app-toast-stack" aria-live="polite" aria-atomic="true">
        {toasts.map(toast => (
          <div key={toast.id} className={`app-toast ${toast.tone}`}>
            <div className="app-toast-icon">{iconForTone(toast.tone)}</div>
            <div>
              <div className="app-toast-title">{toast.title}</div>
              {toast.description && <div className="app-toast-description">{toast.description}</div>}
            </div>
          </div>
        ))}
      </div>

      {dialog && (
        <div className="modal-overlay">
          <div className="modal app-dialog">
            <div className="modal-header">
              <h2 className="modal-title">{dialog.title}</h2>
            </div>
            {dialog.description && (
              <p className="app-dialog-description">{dialog.description}</p>
            )}
            {dialog.mode === 'prompt' && (
              <input
                autoFocus
                className="form-input"
                value={promptValue}
                onChange={(event) => setPromptValue(event.target.value)}
                placeholder={dialog.placeholder}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') {
                    event.preventDefault();
                    closeDialog(promptValue.trim() || null);
                  }
                }}
              />
            )}
            <div className="modal-footer">
              <button type="button" className="btn btn-ghost" onClick={() => closeDialog(dialog.mode === 'confirm' ? false : null)}>
                {dialog.cancelLabel || 'Cancelar'}
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => closeDialog(dialog.mode === 'confirm' ? true : (promptValue.trim() || null))}
              >
                {dialog.confirmLabel || 'Confirmar'}
              </button>
            </div>
          </div>
        </div>
      )}
    </FeedbackContext.Provider>
  );
}

export function useAppFeedback() {
  const context = useContext(FeedbackContext);
  if (!context) {
    throw new Error('useAppFeedback deve ser usado dentro de AppFeedbackProvider');
  }
  return context;
}

function iconForTone(tone: ToastTone) {
  switch (tone) {
    case 'success':
      return <CheckCircle2 size={18} />;
    case 'error':
      return <CircleAlert size={18} />;
    case 'warning':
      return <TriangleAlert size={18} />;
    default:
      return <Info size={18} />;
  }
}

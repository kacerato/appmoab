export default function DashboardLoading() {
  return (
    <div className="loading-page" aria-live="polite" aria-busy="true">
      <div className="spinner" style={{ width: 32, height: 32 }} />
      <span>Preparando conteúdo...</span>
    </div>
  );
}

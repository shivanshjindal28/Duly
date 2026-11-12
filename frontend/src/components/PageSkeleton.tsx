/** Loading placeholder for a whole page: a header bar and a few blocks (skeletons, not spinners). */
export function PageSkeleton({ blocks = 3, label = "Loading" }: { blocks?: number; label?: string }) {
  return (
    <div className="page" aria-busy="true" aria-label={label}>
      <div className="skeleton-row" style={{ height: 18, width: 160 }} />
      <div className="skeleton-row" style={{ height: 30, width: 320 }} />
      {Array.from({ length: blocks }, (_, i) => (
        <div key={i} className="skeleton-row" style={{ height: i === 0 ? 96 : 180 }} />
      ))}
    </div>
  );
}

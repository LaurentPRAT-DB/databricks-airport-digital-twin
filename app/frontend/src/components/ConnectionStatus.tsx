import { useOnlineStatus } from '../hooks/useOnlineStatus';

export function ConnectionStatus() {
  const isOnline = useOnlineStatus();

  if (isOnline) return null;

  return (
    <div className="fixed top-0 left-0 right-0 z-[9999] bg-amber-600 text-white text-center py-1.5 px-4 text-sm font-medium safe-area-top">
      Offline — reconnecting when network returns
    </div>
  );
}

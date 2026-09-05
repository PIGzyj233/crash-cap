import { QueryClient,QueryClientProvider } from '@tanstack/react-query';
import { createContext,useContext,useState,type ReactNode } from 'react';
import type { CrashCapApi } from './client';

const ApiContext = createContext<CrashCapApi | null>(null)
export function ApiProvider({ api, children }: { api: CrashCapApi; children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient({ defaultOptions: { queries: { staleTime: 5_000, retry: 1 } } }))
  return (
    <ApiContext.Provider value={api}>
      <QueryClientProvider client={queryClient}>
        {children}
      </QueryClientProvider>
    </ApiContext.Provider>
  )
}

export function useApi(): CrashCapApi {
  const api = useContext(ApiContext)
  if (!api) throw new Error('useApi must be used inside ApiProvider')
  return api
}

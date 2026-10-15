import { useQueryClient } from '@tanstack/react-query';
import {
  createContext,
  type PropsWithChildren,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';

interface AdminSessionValue {
  token: string | null;
  setToken: (token: string) => void;
  clearToken: () => void;
}

const AdminSessionContext = createContext<AdminSessionValue | null>(null);

export function AdminSessionProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const [token, setTokenState] = useState<string | null>(null);
  // 관리자 신원이 바뀌면 이전 세션의 in-memory query 결과를 재사용하지 않는다.
  // credential 자체는 query key나 storage에 보관하지 않는다.
  const setToken = useCallback((value: string) => {
    queryClient.clear();
    setTokenState(value);
  }, [queryClient]);
  const clearToken = useCallback(() => {
    queryClient.clear();
    setTokenState(null);
  }, [queryClient]);
  const value = useMemo(() => ({ token, setToken, clearToken }), [token, setToken, clearToken]);
  return <AdminSessionContext.Provider value={value}>{children}</AdminSessionContext.Provider>;
}

export function useAdminSession(): AdminSessionValue {
  const value = useContext(AdminSessionContext);
  if (value === null) {
    throw new Error('useAdminSession must be used inside AdminSessionProvider');
  }
  return value;
}

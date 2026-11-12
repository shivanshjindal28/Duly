import { createContext, useContext, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "../api/client";

export type Role = "supplier" | "clerk" | "approver" | "stores" | "auditor" | "admin";

export interface Me {
  id: number;
  email: string;
  full_name: string;
  title: string;
  role: Role;
  approver_level: number | null;
  mfa_enabled: boolean;
  supplier: { id: number; code: string; name: string; msme_category: string } | null;
  permissions: { can: string[]; cannot: string[] };
}

interface AuthValue {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<Me>;
  demoLogin: (email: string) => Promise<Me>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        return await api<Me>("/auth/me");
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });

  const onSession = (me: Me) => {
    qc.clear();
    qc.setQueryData(["me"], me);
    return me;
  };

  const loginMut = useMutation({
    mutationFn: (v: { email: string; password: string }) =>
      api<Me>("/auth/login", { method: "POST", body: JSON.stringify(v) }),
    onSuccess: onSession,
  });
  const demoMut = useMutation({
    mutationFn: (email: string) => api<Me>("/auth/demo-login", { method: "POST", body: JSON.stringify({ email }) }),
    onSuccess: onSession,
  });

  const value: AuthValue = {
    me: meQuery.data ?? null,
    loading: meQuery.isLoading,
    login: (email, password) => loginMut.mutateAsync({ email, password }),
    demoLogin: (email) => demoMut.mutateAsync(email),
    logout: async () => {
      await api<void>("/auth/logout", { method: "POST" });
      qc.clear();
      qc.setQueryData(["me"], null);
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export const ROLE_LABEL: Record<Role, string> = {
  supplier: "Supplier",
  clerk: "AP Clerk",
  approver: "Approver",
  stores: "Stores",
  auditor: "Auditor",
  admin: "Admin",
};

export function roleBadge(me: Me): string {
  return me.role === "approver" && me.approver_level ? `Approver L${me.approver_level}` : ROLE_LABEL[me.role];
}

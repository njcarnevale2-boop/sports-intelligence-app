"use client";

import { createContext, useContext, useEffect, useMemo, useState } from "react";

import { fetchJson } from "./lib/api";

const AuthContext = createContext<{ user: any; setUser: (u: any) => void; logout: () => void }>({ user: null, setUser: () => {}, logout: () => {} });

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<any>(null);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return;

    fetchJson<any>("/api/auth/me", {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((payload) => setUser(payload))
      .catch(() => setUser(null));
  }, []);

  const logout = () => {
    localStorage.removeItem("access_token");
    localStorage.removeItem("refresh_token");
    setUser(null);
  };

  const value = useMemo(() => ({ user, setUser, logout }), [user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

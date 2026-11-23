"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { api, getToken, setToken } from "./api";
import type { Cart, User } from "./types";

interface AuthOut { token: string; user: User; store_slug: string | null }
interface Ctx {
  user: User | null; storeSlug: string | null; ready: boolean; cartCount: number;
  login: (email: string, password: string) => Promise<User>;
  register: (data: Record<string, unknown>) => Promise<User>;
  logout: () => void; refreshCart: () => Promise<void>; setUser: (u: User) => void;
}

const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUserState] = useState<User | null>(null);
  const [storeSlug, setStoreSlug] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [cartCount, setCartCount] = useState(0);

  const refreshCart = useCallback(async () => {
    try { const c = await api<Cart>("/api/cart"); setCartCount(c.item_count); } catch { setCartCount(0); }
  }, []);

  const accept = useCallback((out: AuthOut) => {
    setToken(out.token); setUserState(out.user); setStoreSlug(out.store_slug);
    if (out.user.role === "customer") refreshCart();
    return out.user;
  }, [refreshCart]);

  useEffect(() => {
    if (!getToken()) { setReady(true); return; }
    api<AuthOut>("/api/auth/me").then(accept).catch(() => setToken(null)).finally(() => setReady(true));
  }, [accept]);

  const value: Ctx = {
    user, storeSlug, ready, cartCount, refreshCart,
    setUser: (u) => setUserState(u),
    login: async (email, password) => accept(await api<AuthOut>("/api/auth/login", { method: "POST", body: { email, password }, auth: false })),
    register: async (data) => accept(await api<AuthOut>("/api/auth/register", { method: "POST", body: data, auth: false })),
    logout: () => { setToken(null); setUserState(null); setStoreSlug(null); setCartCount(0); },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

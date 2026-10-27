"use client";

import { createContext,useCallback,useContext,useEffect,useState } from "react";

import { api,ApiError,setActiveOrganizationId } from "@/lib/api";
import type { User,UserRole } from "@/types/auth";

interface RegisterInput {
  email: string;
  password: string;
  full_name: string;
  role: UserRole;
}

interface LoginInput {
  email: string;
  password: string;
}

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (input: LoginInput) => Promise<User>;
  register: (input: RegisterInput) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const me = await api.get<User>("/api/v1/auth/me");
      setUser(me);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetch the current session once on mount. This is the standard
    // "check auth on load" pattern — there's no simpler render-time
    // alternative since it depends on an external cookie-backed session.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
  }, [refresh]);

  const login = useCallback(async (input: LoginInput) => {
    const loggedInUser = await api.post<User>("/api/v1/auth/login", input);
    setActiveOrganizationId(null);
    setUser(loggedInUser);
    return loggedInUser;
  }, []);

  const register = useCallback(async (input: RegisterInput) => {
    const newUser = await api.post<User>("/api/v1/auth/register", input);
    setActiveOrganizationId(null);
    setUser(newUser);
    return newUser;
  }, []);

  const logout = useCallback(async () => {
    await api.post("/api/v1/auth/logout");
    setActiveOrganizationId(null);
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, register, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return ctx;
}

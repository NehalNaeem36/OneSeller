"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useAuth } from "@/lib/auth";
import type { Role } from "@/lib/types";
import { Loading } from "./ui";

export default function RequireRole({ role, children }: { role: Role; children: React.ReactNode }) {
  const { user, ready } = useAuth();
  const router = useRouter();
  useEffect(() => {
    if (!ready) return;
    if (!user) router.replace(`/login?next=${encodeURIComponent(window.location.pathname)}`);
    else if (user.role !== role) router.replace(user.role === "seller" ? "/seller" : "/");
  }, [ready, user, role, router]);
  if (!ready || !user || user.role !== role) return <Loading />;
  return <>{children}</>;
}

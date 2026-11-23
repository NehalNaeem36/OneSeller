"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { StoreCard } from "@/lib/types";
import StoreTile from "@/components/StoreTile";
import { Empty, Loading } from "@/components/ui";

export default function StoresPage() {
  const [q, setQ] = useState("");
  const [stores, setStores] = useState<StoreCard[] | null>(null);
  useEffect(() => {
    const t = setTimeout(() => api<StoreCard[]>("/api/stores", { auth: false, query: { q } }).then(setStores).catch(() => setStores([])), 250);
    return () => clearTimeout(t);
  }, [q]);
  return (
    <div>
      <h1 className="text-2xl font-semibold">Stores</h1>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search stores…"
        className="mt-4 w-full max-w-md rounded-lg border border-slate-300 px-4 py-2 text-sm outline-none focus:border-brand-500" />
      <div className="mt-6">
        {!stores ? <Loading /> : stores.length ? (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{stores.map((s) => <StoreTile key={s.id} s={s} />)}</div>
        ) : <Empty title="No stores found" />}
      </div>
    </div>
  );
}

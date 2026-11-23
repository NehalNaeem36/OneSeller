"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Product } from "@/lib/types";
import { ProductGrid } from "@/components/ProductCard";
import { Alert, Button, Empty, Input, Loading, Select } from "@/components/ui";

const KEYS = ["q", "category", "color", "size", "min_price", "max_price", "store", "in_stock", "sort"] as const;
type Filters = Record<(typeof KEYS)[number], string>;

function SearchInner() {
  const sp = useSearchParams();
  const router = useRouter();
  const initial = Object.fromEntries(KEYS.map((k) => [k, sp.get(k) || ""])) as Filters;
  const [f, setF] = useState<Filters>(initial);
  const [page, setPage] = useState(1);
  const [res, setRes] = useState<{ items: Product[]; total: number } | null>(null);
  const [cats, setCats] = useState<{ name: string }[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => { api<{ name: string }[]>("/api/categories", { auth: false }).then(setCats).catch(() => {}); }, []);
  useEffect(() => {
    const cur = Object.fromEntries(KEYS.map((k) => [k, sp.get(k) || ""])) as Filters;
    setF(cur);
    setRes(null); setErr("");
    api<{ items: Product[]; total: number }>("/api/products", { auth: false, query: { ...cur, in_stock: cur.in_stock === "1", page, page_size: 24 } })
      .then(setRes).catch((e) => setErr(e.message));
  }, [sp, page]);

  function apply(e?: React.FormEvent) {
    e?.preventDefault();
    const qs = new URLSearchParams();
    KEYS.forEach((k) => f[k] && qs.set(k, f[k]));
    setPage(1);
    router.push(`/search?${qs.toString()}`);
  }
  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value });

  return (
    <div className="grid gap-6 lg:grid-cols-[260px_1fr]">
      <form onSubmit={apply} className="h-fit space-y-3 rounded-xl border border-slate-200 bg-white p-4 lg:sticky lg:top-20">
        <h2 className="font-semibold">Filters</h2>
        <Input label="Keywords" value={f.q} onChange={set("q")} placeholder="e.g. oxford shirt" />
        <Select label="Category" value={f.category} onChange={set("category")}>
          <option value="">All categories</option>
          {cats.map((c) => <option key={c.name}>{c.name}</option>)}
        </Select>
        <div className="grid grid-cols-2 gap-2">
          <Input label="Color" value={f.color} onChange={set("color")} placeholder="black" />
          <Input label="Size" value={f.size} onChange={set("size")} placeholder="M" />
          <Input label="Min Rs." type="number" min={0} value={f.min_price} onChange={set("min_price")} />
          <Input label="Max Rs." type="number" min={0} value={f.max_price} onChange={set("max_price")} />
        </div>
        <Input label="Store" value={f.store} onChange={set("store")} placeholder="Store name" />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={f.in_stock === "1"} onChange={(e) => setF({ ...f, in_stock: e.target.checked ? "1" : "" })} /> In stock only
        </label>
        <Select label="Sort" value={f.sort} onChange={set("sort")}>
          <option value="">Relevance</option><option value="price_asc">Price: low to high</option>
          <option value="price_desc">Price: high to low</option><option value="newest">Newest</option>
        </Select>
        <div className="flex gap-2">
          <Button type="submit" className="flex-1">Apply</Button>
          <Button type="button" variant="secondary" onClick={() => router.push("/search")}>Reset</Button>
        </div>
      </form>
      <div>
        <p className="mb-4 text-sm text-slate-500">{res ? `${res.total} result${res.total === 1 ? "" : "s"}` : "Searching…"}</p>
        {err && <Alert>{err}</Alert>}
        {!res && !err && <Loading />}
        {res && (res.items.length ? <ProductGrid items={res.items} /> : <Empty title="No products match these filters">Try removing a filter or ask the AI assistant.</Empty>)}
        {res && res.total > 24 && (
          <div className="mt-6 flex justify-center gap-2">
            <Button variant="secondary" size="sm" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</Button>
            <span className="px-3 py-1.5 text-sm">Page {page}</span>
            <Button variant="secondary" size="sm" disabled={page * 24 >= res.total} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function SearchPage() {
  return <Suspense fallback={<Loading />}><SearchInner /></Suspense>;
}

"use client";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { api, imageSrc } from "@/lib/api";
import type { Product, StoreCard } from "@/lib/types";
import { ProductGrid } from "@/components/ProductCard";
import { Alert, Badge, Empty, Loading } from "@/components/ui";

export default function StorefrontPage() {
  const { slug } = useParams<{ slug: string }>();
  const [store, setStore] = useState<StoreCard | null>(null);
  const [products, setProducts] = useState<Product[] | null>(null);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => { api<StoreCard>(`/api/stores/${slug}`, { auth: false }).then(setStore).catch((e) => setErr(e.message)); }, [slug]);
  useEffect(() => {
    if (!store) return;
    const t = setTimeout(() => api<{ items: Product[] }>("/api/products", { auth: false, query: { store: store.slug, q, page_size: 60 } })
      .then((r) => setProducts(r.items)).catch((e) => setErr(e.message)), 200);
    return () => clearTimeout(t);
  }, [store, q]);

  if (err) return <Alert>{err === "Store not found" ? "This store doesn't exist or is not currently active." : err}</Alert>;
  if (!store) return <Loading />;
  const logo = imageSrc(store.logo_url);
  return (
    <div>
      <section className="rounded-3xl px-6 py-10 text-white sm:px-10" style={{ background: `linear-gradient(135deg, ${store.brand_color}, #0f172a)` }}>
        <div className="flex items-center gap-4">
          {logo ? <img src={logo} alt="" className="h-16 w-16 rounded-xl bg-white object-cover" />
            : <span className="flex h-16 w-16 items-center justify-center rounded-xl bg-white/20 text-2xl font-bold">{store.name[0]}</span>}
          <div>
            <h1 className="flex items-center gap-2 text-3xl font-bold">{store.name} {store.premium && <Badge tone="brand">★ Premium</Badge>}</h1>
            {store.tagline && <p className="text-white/80">{store.tagline}</p>}
          </div>
        </div>
        {store.description && <p className="mt-4 max-w-2xl text-sm text-white/80">{store.description}</p>}
        <p className="mt-4 text-xs text-white/60">Share this store: /store/{store.slug} · Ask the AI assistant about any product here.</p>
      </section>
      <div className="mt-6 flex items-center justify-between gap-4">
        <h2 className="text-xl font-semibold">Products ({products?.length ?? "…"})</h2>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={`Search ${store.name}…`}
          className="w-full max-w-xs rounded-lg border border-slate-300 px-3 py-2 text-sm outline-none focus:border-brand-500" />
      </div>
      <div className="mt-4">{!products ? <Loading /> : products.length ? <ProductGrid items={products} /> : <Empty title="No products found" />}</div>
    </div>
  );
}

"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Product, StoreCard } from "@/lib/types";
import { ProductGrid } from "@/components/ProductCard";
import { Alert, Badge, Loading } from "@/components/ui";
import StoreTile from "@/components/StoreTile";

interface Home {
  premium_products: Product[]; top_seller_products: Product[]; featured_products: Product[];
  categories: { name: string; count: number }[]; stores: StoreCard[]; top_stores: StoreCard[];
}

function Section({ title, badge, children, href }: { title: string; badge?: React.ReactNode; children: React.ReactNode; href?: string }) {
  return (
    <section className="mt-10">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-xl font-semibold">{title} {badge}</h2>
        {href && <Link href={href} className="text-sm text-brand-600 hover:underline">View all →</Link>}
      </div>
      {children}
    </section>
  );
}

export default function HomePage() {
  const [data, setData] = useState<Home | null>(null);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const router = useRouter();
  useEffect(() => { api<Home>("/api/home", { auth: false }).then(setData).catch((e) => setErr(e.message)); }, []);

  return (
    <div>
      <section className="overflow-hidden rounded-3xl bg-gradient-to-br from-brand-700 via-brand-600 to-sky-500 px-6 py-12 text-white sm:px-12">
        <p className="text-sm font-medium uppercase tracking-wider text-brand-100">One Agent for every Seller</p>
        <h1 className="mt-2 max-w-2xl text-3xl font-bold sm:text-5xl">Shop small stores with an AI sales rep that knows every product.</h1>
        <p className="mt-3 max-w-xl text-brand-100">Ask in plain language — &ldquo;black shirts under Rs. 3000 in medium&rdquo; — compare options, and check out in chat.</p>
        <form className="mt-6 flex max-w-xl gap-2" onSubmit={(e) => { e.preventDefault(); router.push(`/search?q=${encodeURIComponent(q)}`); }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="What are you looking for?"
            className="flex-1 rounded-xl px-4 py-3 text-slate-900 outline-none" />
          <button className="rounded-xl bg-slate-900 px-5 font-medium hover:bg-slate-800">Search</button>
        </form>
        <div className="mt-6 flex flex-wrap gap-3 text-sm">
          <Link href="/register?role=seller" className="rounded-lg bg-white/15 px-3 py-1.5 hover:bg-white/25">Sell on OneSeller — 1 month free →</Link>
        </div>
      </section>

      {err && <div className="mt-6"><Alert>{err}</Alert></div>}
      {!data && !err && <Loading />}
      {data && <>
        {data.categories.length > 0 && (
          <Section title="Shop by category">
            <div className="flex flex-wrap gap-2">
              {data.categories.map((c) => (
                <Link key={c.name} href={`/search?category=${encodeURIComponent(c.name)}`}
                  className="rounded-full border border-slate-200 bg-white px-4 py-2 text-sm hover:border-brand-500 hover:text-brand-700">
                  {c.name} <span className="text-slate-400">{c.count}</span>
                </Link>))}
            </div>
          </Section>
        )}
        {data.premium_products.length > 0 && (
          <Section title="From premium sellers" badge={<Badge tone="brand">Sponsored placement</Badge>}>
            <ProductGrid items={data.premium_products.slice(0, 4)} />
          </Section>
        )}
        {data.top_seller_products.length > 0 && (
          <Section title="Popular with shoppers" badge={<Badge tone="green">Top-selling stores</Badge>}>
            <ProductGrid items={data.top_seller_products.slice(0, 4)} />
          </Section>
        )}
        <Section title="New arrivals" href="/search?sort=newest">
          {data.featured_products.length ? <ProductGrid items={data.featured_products} /> : <p className="text-slate-500">No products yet.</p>}
        </Section>
        {data.stores.length > 0 && (
          <Section title="Stores" href="/stores">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {data.stores.map((s) => <StoreTile key={s.id} s={s} />)}
            </div>
          </Section>
        )}
      </>}
    </div>
  );
}

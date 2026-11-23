import Link from "next/link";
import type { Product } from "@/lib/types";
import { rs } from "@/lib/format";
import ProductImage from "./ProductImage";
import { Badge } from "./ui";

export default function ProductCard({ p }: { p: Product }) {
  return (
    <Link href={`/product/${p.id}`} className="group flex flex-col overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-md">
      <div className="relative">
        <ProductImage url={p.image_url} name={p.name} className="aspect-[4/3] w-full" />
        {p.store?.premium && <span className="absolute left-2 top-2"><Badge tone="brand">★ Premium seller</Badge></span>}
      </div>
      <div className="flex flex-1 flex-col gap-1 p-3">
        <p className="text-xs text-slate-500">{p.store?.name} · {p.category}</p>
        <p className="line-clamp-2 font-medium text-slate-900 group-hover:text-brand-700">{p.name}</p>
        <div className="mt-auto flex items-center justify-between pt-2">
          <span className="font-semibold">{rs(p.price)}</span>
          {p.in_stock ? (p.stock <= 5 ? <Badge tone="amber">Only {p.stock} left</Badge> : <Badge tone="green">In stock</Badge>)
            : <Badge tone="red">Out of stock</Badge>}
        </div>
      </div>
    </Link>
  );
}

export function ProductGrid({ items }: { items: Product[] }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
      {items.map((p) => <ProductCard key={p.id} p={p} />)}
    </div>
  );
}

import Link from "next/link";
import type { StoreCard } from "@/lib/types";
import { Badge } from "./ui";

export default function StoreTile({ s }: { s: StoreCard }) {
  return (
    <Link href={`/store/${s.slug}`} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:shadow-md">
      <div className="flex items-center gap-3">
        <span className="flex h-10 w-10 items-center justify-center rounded-lg font-bold text-white" style={{ background: s.brand_color }}>{s.name[0]}</span>
        <div className="min-w-0">
          <p className="truncate font-medium">{s.name}</p>
          <p className="text-xs text-slate-500">{s.product_count} products</p>
        </div>
        {s.premium && <span className="ml-auto"><Badge tone="brand">★ Premium</Badge></span>}
      </div>
      {s.tagline && <p className="mt-3 line-clamp-2 text-sm text-slate-600">{s.tagline}</p>}
    </Link>
  );
}

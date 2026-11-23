"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, rs } from "@/lib/format";
import type { Product } from "@/lib/types";
import ProductImage from "@/components/ProductImage";
import { Alert, Badge, Button, Loading } from "@/components/ui";

function Picker({ label, options, value, onChange }: { label: string; options: string[]; value: string; onChange: (v: string) => void }) {
  if (!options.length) return null;
  return (
    <div>
      <p className="mb-2 text-sm font-medium">{label}</p>
      <div className="flex flex-wrap gap-2">
        {options.map((o) => (
          <button key={o} type="button" onClick={() => onChange(o)}
            className={cx("rounded-lg border px-3 py-1.5 text-sm capitalize", value === o ? "border-brand-600 bg-brand-50 text-brand-700" : "border-slate-300 hover:border-slate-400")}>{o}</button>))}
      </div>
    </div>
  );
}

export default function ProductPage() {
  const { id } = useParams<{ id: string }>();
  const { user, refreshCart } = useAuth();
  const router = useRouter();
  const [p, setP] = useState<Product | null>(null);
  const [err, setErr] = useState("");
  const [color, setColor] = useState("");
  const [size, setSize] = useState("");
  const [qty, setQty] = useState(1);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api<Product>(`/api/products/${id}`, { auth: false }).then((d) => {
      setP(d);
      if (d.colors.length === 1) setColor(d.colors[0]);
      if (d.sizes.length === 1) setSize(d.sizes[0]);
    }).catch((e) => setErr(e.message));
  }, [id]);

  async function add() {
    if (!p) return;
    if (!user) return router.push(`/login?next=/product/${p.id}`);
    if (user.role !== "customer") return setMsg({ tone: "red", text: "Switch to a customer account to shop." });
    if (p.colors.length > 1 && !color) return setMsg({ tone: "red", text: "Please choose a color." });
    if (p.sizes.length > 1 && !size) return setMsg({ tone: "red", text: "Please choose a size." });
    setBusy(true); setMsg(null);
    try {
      await api("/api/cart/items", { method: "POST", body: { product_id: p.id, quantity: qty, color: color || null, size: size || null } });
      await refreshCart();
      setMsg({ tone: "green", text: "Added to your cart." });
    } catch (e) {
      setMsg({ tone: "red", text: e instanceof ApiError ? e.message : "Could not add to cart." });
    } finally { setBusy(false); }
  }

  if (err) return <Alert>{err}</Alert>;
  if (!p) return <Loading />;
  return (
    <div className="grid gap-8 md:grid-cols-2">
      <ProductImage url={p.image_url} name={p.name} className="aspect-square w-full rounded-2xl border border-slate-200" />
      <div className="space-y-5">
        <div>
          {p.store && <Link href={`/store/${p.store.slug}`} className="text-sm text-brand-600 hover:underline">{p.store.name}</Link>}
          <h1 className="mt-1 text-3xl font-bold">{p.name}</h1>
          <p className="mt-1 text-sm text-slate-500">{p.category}</p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-2xl font-semibold">{rs(p.price)}</span>
          {p.in_stock ? <Badge tone={p.stock <= 5 ? "amber" : "green"}>{p.stock} in stock</Badge> : <Badge tone="red">Out of stock</Badge>}
        </div>
        {p.description && <p className="text-slate-600">{p.description}</p>}
        <Picker label="Color" options={p.colors} value={color} onChange={setColor} />
        <Picker label="Size" options={p.sizes} value={size} onChange={setSize} />
        <div className="flex items-center gap-3">
          <label className="text-sm font-medium">Qty</label>
          <input type="number" min={1} max={Math.max(1, p.stock)} value={qty}
            onChange={(e) => setQty(Math.max(1, Math.min(p.stock || 1, Number(e.target.value) || 1)))}
            className="w-20 rounded-lg border border-slate-300 px-3 py-2 text-sm" />
        </div>
        {msg && <Alert tone={msg.tone}>{msg.text} {msg.tone === "green" && <Link href="/cart" className="font-medium underline">View cart</Link>}</Alert>}
        <Button onClick={add} loading={busy} disabled={!p.in_stock} className="w-full sm:w-auto">{p.in_stock ? "Add to cart" : "Out of stock"}</Button>
      </div>
    </div>
  );
}

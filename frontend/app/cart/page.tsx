"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { rs } from "@/lib/format";
import type { Cart } from "@/lib/types";
import ProductImage from "@/components/ProductImage";
import RequireRole from "@/components/RequireRole";
import { Alert, Button, Card, Empty, Loading } from "@/components/ui";

function CartInner() {
  const { refreshCart } = useAuth();
  const [cart, setCart] = useState<Cart | null>(null);
  const [err, setErr] = useState("");
  const load = useCallback(() => api<Cart>("/api/cart").then(setCart).catch((e) => setErr(e.message)), []);
  useEffect(() => { load(); }, [load]);

  async function mutate(fn: () => Promise<Cart>) {
    setErr("");
    try { setCart(await fn()); refreshCart(); } catch (e) { setErr(e instanceof ApiError ? e.message : "Update failed"); }
  }

  if (!cart) return err ? <Alert>{err}</Alert> : <Loading />;
  return (
    <div>
      <h1 className="text-2xl font-semibold">Your cart</h1>
      {err && <div className="mt-4"><Alert>{err}</Alert></div>}
      {cart.items.length === 0 ? (
        <div className="mt-6"><Empty title="Your cart is empty"><Link href="/" className="text-brand-600 underline">Continue shopping</Link> or ask the AI assistant.</Empty></div>
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_320px]">
          <div className="space-y-3">
            {cart.items.map((i) => (
              <Card key={i.item_id} className="flex gap-4 p-3">
                <ProductImage url={i.image_url} name={i.name} className="h-20 w-20 shrink-0 rounded-lg" />
                <div className="min-w-0 flex-1">
                  <Link href={`/product/${i.product_id}`} className="font-medium hover:text-brand-700">{i.name}</Link>
                  <p className="text-xs text-slate-500">{i.store.name}{i.color ? ` · ${i.color}` : ""}{i.size ? ` · Size ${i.size}` : ""}</p>
                  {!i.available && <p className="text-xs text-red-600">Only {i.stock} available</p>}
                  <div className="mt-2 flex items-center gap-3">
                    <input type="number" min={1} max={100} value={i.quantity} aria-label="Quantity"
                      onChange={(e) => { const q = Number(e.target.value); if (q >= 1) mutate(() => api<Cart>(`/api/cart/items/${i.item_id}`, { method: "PATCH", body: { quantity: q } })); }}
                      className="w-16 rounded-md border border-slate-300 px-2 py-1 text-sm" />
                    <button onClick={() => mutate(() => api<Cart>(`/api/cart/items/${i.item_id}`, { method: "DELETE" }))} className="text-sm text-red-600 hover:underline">Remove</button>
                  </div>
                </div>
                <p className="font-semibold">{rs(i.subtotal)}</p>
              </Card>
            ))}
          </div>
          <Card className="h-fit space-y-3 p-4">
            <div className="flex justify-between text-sm"><span>Items</span><span>{cart.item_count}</span></div>
            <div className="flex justify-between text-lg font-semibold"><span>Total</span><span>{rs(cart.total)}</span></div>
            {new Set(cart.items.map((i) => i.store.id)).size > 1 && <p className="text-xs text-slate-500">Items from multiple stores are split into one order per store.</p>}
            {cart.issues.length > 0 && <Alert tone="amber">{cart.issues.join("; ")}</Alert>}
            <Link href="/checkout" className={cart.issues.length ? "pointer-events-none opacity-50" : ""}><Button className="w-full">Proceed to checkout</Button></Link>
          </Card>
        </div>
      )}
    </div>
  );
}

export default function CartPage() { return <RequireRole role="customer"><CartInner /></RequireRole>; }

"use client";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { api, ApiError, imageSrc } from "@/lib/api";
import { cx, rs } from "@/lib/format";
import type { Product } from "@/lib/types";
import ProductImage from "@/components/ProductImage";
import { Alert, Badge, Button, Card, Empty, Input, Loading, Modal, Select, Textarea } from "@/components/ui";

type Form = { name: string; category: string; price: string; stock: string; colors: string; sizes: string; sku: string;
  description: string; image_id: number | null; image_url: string | null };
const EMPTY: Form = { name: "", category: "", price: "", stock: "", colors: "", sizes: "", sku: "", description: "", image_id: null, image_url: null };

function ProductForm({ initial, onSaved, onCancel }: { initial: Product | null; onSaved: () => void; onCancel: () => void }) {
  const [f, setF] = useState<Form>(initial ? {
    name: initial.name, category: initial.category, price: String(initial.price), stock: String(initial.stock),
    colors: initial.colors.join(", "), sizes: initial.sizes.join(", "), sku: initial.sku || "", description: initial.description || "",
    image_id: initial.image_id ?? null, image_url: initial.image_url ?? null } : EMPTY);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const set = (k: keyof Form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });

  async function upload(file: File) {
    setErr("");
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await api<{ image_id: number; url: string }>("/api/seller/images", { method: "POST", body: fd });
      setF((x) => ({ ...x, image_id: r.image_id, image_url: r.url }));
    } catch (e) { setErr(e instanceof ApiError ? e.message : "Upload failed"); }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr("");
    const split = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);
    const body = { name: f.name, category: f.category, price: Number(f.price), stock: Number(f.stock), colors: split(f.colors),
      sizes: split(f.sizes), sku: f.sku || null, description: f.description || null, image_id: f.image_id };
    try {
      await api(initial ? `/api/seller/products/${initial.id}` : "/api/seller/products", { method: initial ? "PUT" : "POST", body });
      onSaved();
    } catch (er) { setErr(er instanceof ApiError ? er.message : "Save failed"); } finally { setBusy(false); }
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      {err && <Alert>{err}</Alert>}
      <div className="flex items-center gap-4">
        {f.image_url ? <img src={imageSrc(f.image_url)!} alt="" className="h-20 w-20 rounded-lg object-cover" /> : <ProductImage name={f.name || "New"} className="h-20 w-20 rounded-lg" />}
        <label className="cursor-pointer text-sm text-brand-600 hover:underline">
          {f.image_url ? "Change image" : "Upload image"} (JPG/PNG/WEBP, max 2 MB)
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        </label>
      </div>
      <Input label="Name" value={f.name} onChange={set("name")} required />
      <div className="grid grid-cols-2 gap-3">
        <Input label="Category" value={f.category} onChange={set("category")} placeholder="Shirts" required />
        <Input label="SKU (optional)" value={f.sku} onChange={set("sku")} />
        <Input label="Price (Rs.)" type="number" min={1} step="0.01" value={f.price} onChange={set("price")} required />
        <Input label="Stock" type="number" min={0} value={f.stock} onChange={set("stock")} required />
        <Input label="Colors (comma separated)" value={f.colors} onChange={set("colors")} placeholder="black, white" />
        <Input label="Sizes (comma separated)" value={f.sizes} onChange={set("sizes")} placeholder="S, M, L" />
      </div>
      <Textarea label="Description" rows={3} value={f.description} onChange={set("description")} />
      <div className="flex justify-end gap-2">
        <Button type="button" variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button loading={busy}>{initial ? "Save changes" : "Create product"}</Button>
      </div>
    </form>
  );
}

function ProductsInner() {
  const sp = useSearchParams();
  const [status, setStatus] = useState<"active" | "deleted" | "all">("active");
  const [q, setQ] = useState("");
  const [items, setItems] = useState<Product[] | null>(null);
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [editing, setEditing] = useState<Product | null | "new">(sp.get("new") ? "new" : null);
  const [hardTarget, setHardTarget] = useState<Product | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [bulk, setBulk] = useState({ action: "", value: "" });
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);

  const load = useCallback(() => {
    api<Product[]>("/api/seller/products", { query: { status, q } }).then((r) => { setItems(r); setSel(new Set()); })
      .catch((e) => setMsg({ tone: "red", text: e.message }));
  }, [status, q]);
  useEffect(() => { const t = setTimeout(load, 200); return () => clearTimeout(t); }, [load]);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ tone: "green", text: ok }); load(); }
    catch (e) { setMsg({ tone: "red", text: e instanceof ApiError ? e.message : "Action failed" }); }
  }

  const toggle = (id: number) => setSel((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const allSelected = !!items?.length && sel.size === items.length;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Products</h1>
        <Button onClick={() => setEditing("new")}>+ Add product</Button>
      </div>
      {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex rounded-lg border border-slate-200 bg-white p-1 text-sm">
          {(["active", "deleted", "all"] as const).map((s) => (
            <button key={s} onClick={() => setStatus(s)} className={cx("rounded-md px-3 py-1 capitalize", status === s ? "bg-slate-900 text-white" : "")}>
              {s === "deleted" ? "Deleted (recoverable)" : s}</button>))}
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search by name…" className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm" />
      </div>

      {sel.size > 0 && (
        <Card className="flex flex-wrap items-end gap-3 p-3">
          <span className="text-sm font-medium">{sel.size} selected</span>
          <Select value={bulk.action} onChange={(e) => setBulk({ action: e.target.value, value: "" })} className="w-48">
            <option value="">Bulk action…</option>
            <option value="soft_delete">Delete (soft, recoverable)</option>
            <option value="restore">Restore</option>
            <option value="set_stock">Set stock</option>
            <option value="adjust_price_percent">Adjust price by %</option>
            <option value="set_category">Set category</option>
          </Select>
          {["set_stock", "adjust_price_percent", "set_category"].includes(bulk.action) && (
            <input value={bulk.value} onChange={(e) => setBulk({ ...bulk, value: e.target.value })} className="w-40 rounded-lg border border-slate-300 px-3 py-2 text-sm"
              placeholder={bulk.action === "set_category" ? "Category" : bulk.action === "set_stock" ? "e.g. 20" : "e.g. -10"} />)}
          <Button size="sm" disabled={!bulk.action} onClick={() => run(() => api("/api/seller/products/bulk", { method: "POST",
            body: { product_ids: [...sel], action: bulk.action, value: bulk.action === "set_category" ? bulk.value : bulk.value ? Number(bulk.value) : null } }),
            "Bulk update applied.")}>Apply</Button>
        </Card>
      )}

      {!items ? <Loading /> : items.length === 0 ? <Empty title="No products here">Add products one by one or import a CSV/XLSX file.</Empty> : (
        <Card className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase text-slate-500">
              <tr>
                <th className="p-3"><input type="checkbox" checked={allSelected} onChange={() => setSel(allSelected ? new Set() : new Set(items.map((p) => p.id)))} aria-label="Select all" /></th>
                <th className="p-3">Product</th><th className="p-3">Category</th><th className="p-3">Price</th><th className="p-3">Stock</th>
                <th className="p-3">Variants</th><th className="p-3">Status</th><th className="p-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {items.map((p) => (
                <tr key={p.id} className={sel.has(p.id) ? "bg-brand-50/50" : ""}>
                  <td className="p-3"><input type="checkbox" checked={sel.has(p.id)} onChange={() => toggle(p.id)} aria-label={`Select ${p.name}`} /></td>
                  <td className="p-3"><div className="flex items-center gap-3"><ProductImage url={p.image_url} name={p.name} className="h-10 w-10 rounded-md" />
                    <div><p className="font-medium">{p.name}</p>{p.sku && <p className="text-xs text-slate-400">{p.sku}</p>}</div></div></td>
                  <td className="p-3">{p.category}</td>
                  <td className="p-3">{rs(p.price)}</td>
                  <td className="p-3"><span className={p.low_stock ? "font-medium text-red-600" : ""}>{p.stock}</span></td>
                  <td className="p-3 text-xs text-slate-500">{[p.colors.join("/"), p.sizes.join("/")].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="p-3">{p.is_active ? <Badge tone="green">Active</Badge> : <Badge tone="slate">Deleted</Badge>}</td>
                  <td className="whitespace-nowrap p-3 text-right">
                    {p.is_active ? <>
                      <button onClick={() => setEditing(p)} className="mr-3 text-brand-600 hover:underline">Edit</button>
                      <button onClick={() => run(() => api(`/api/seller/products/${p.id}`, { method: "DELETE" }), `"${p.name}" moved to Deleted (recoverable).`)} className="text-red-600 hover:underline">Delete</button>
                    </> : <>
                      <button onClick={() => run(() => api(`/api/seller/products/${p.id}/restore`, { method: "POST" }), `"${p.name}" restored.`)} className="mr-3 text-brand-600 hover:underline">Restore</button>
                      <button onClick={() => { setHardTarget(p); setConfirmText(""); }} className="text-red-700 hover:underline">Delete permanently</button>
                    </>}
                  </td>
                </tr>))}
            </tbody>
          </table>
        </Card>
      )}

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={editing === "new" ? "Add product" : "Edit product"} wide>
        {editing !== null && <ProductForm initial={editing === "new" ? null : editing} onCancel={() => setEditing(null)}
          onSaved={() => { setEditing(null); setMsg({ tone: "green", text: "Product saved." }); load(); }} />}
      </Modal>

      <Modal open={!!hardTarget} onClose={() => setHardTarget(null)} title="Delete permanently?">
        {hardTarget && <div className="space-y-4 text-sm">
          <p>This permanently removes <strong>{hardTarget.name}</strong>. It cannot be undone. Past orders keep their product name and price.</p>
          <p>Products in orders that are still open can&apos;t be permanently deleted.</p>
          <Input label={`Type "${hardTarget.name}" to confirm`} value={confirmText} onChange={(e) => setConfirmText(e.target.value)} />
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setHardTarget(null)}>Cancel</Button>
            <Button variant="danger" disabled={confirmText !== hardTarget.name} onClick={() => {
              const t = hardTarget; setHardTarget(null);
              run(() => api(`/api/seller/products/${t.id}`, { method: "DELETE", query: { hard: true, confirm: true } }), `"${t.name}" permanently deleted.`);
            }}>Delete permanently</Button>
          </div>
        </div>}
      </Modal>
    </div>
  );
}

export default function ProductsPage() { return <Suspense fallback={<Loading />}><ProductsInner /></Suspense>; }

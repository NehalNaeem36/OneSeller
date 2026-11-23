"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError, imageSrc } from "@/lib/api";
import { Alert, Button, Card, Input, Loading, Textarea } from "@/components/ui";

interface StoreF { name: string; slug: string; tagline: string | null; description: string | null; brand_color: string;
  logo_image_id: number | null; logo_url: string | null }

export default function StoreSettings() {
  const [s, setS] = useState<StoreF | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  useEffect(() => { api<StoreF>("/api/seller/store").then(setS).catch((e) => setMsg({ tone: "red", text: e.message })); }, []);
  if (!s) return msg ? <Alert>{msg.text}</Alert> : <Loading />;

  async function upload(file: File) {
    const fd = new FormData(); fd.append("file", file);
    try { const r = await api<{ image_id: number; url: string }>("/api/seller/images", { method: "POST", body: fd });
      setS((x) => x && { ...x, logo_image_id: r.image_id, logo_url: r.url }); }
    catch (e) { setMsg({ tone: "red", text: e instanceof ApiError ? e.message : "Upload failed" }); }
  }
  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null);
    try {
      setS(await api<StoreF>("/api/seller/store", { method: "PUT", body: { name: s!.name, tagline: s!.tagline || null,
        description: s!.description || null, brand_color: s!.brand_color, logo_image_id: s!.logo_image_id } }));
      setMsg({ tone: "green", text: "Storefront updated." });
    } catch (er) { setMsg({ tone: "red", text: er instanceof ApiError ? er.message : "Save failed" }); } finally { setBusy(false); }
  }
  return (
    <div className="mx-auto grid max-w-5xl gap-6 lg:grid-cols-2">
      <Card className="p-6">
        <h1 className="text-lg font-semibold">Customize storefront</h1>
        <p className="mb-4 text-sm text-slate-500">Public URL: <Link className="text-brand-600 underline" href={`/store/${s.slug}`}>/store/{s.slug}</Link></p>
        <form onSubmit={save} className="space-y-3">
          {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
          <Input label="Store name" value={s.name} onChange={(e) => setS({ ...s, name: e.target.value })} required />
          <Input label="Tagline" value={s.tagline || ""} onChange={(e) => setS({ ...s, tagline: e.target.value })} />
          <Textarea label="Description" rows={4} value={s.description || ""} onChange={(e) => setS({ ...s, description: e.target.value })} />
          <label className="flex items-center gap-3 text-sm font-medium">Brand color
            <input type="color" value={s.brand_color} onChange={(e) => setS({ ...s, brand_color: e.target.value })} className="h-9 w-16 rounded" /></label>
          <label className="block cursor-pointer text-sm text-brand-600 hover:underline">Upload logo
            <input type="file" accept="image/png,image/jpeg,image/webp" className="hidden" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
          <Button loading={busy}>Save</Button>
        </form>
      </Card>
      <div>
        <p className="mb-2 text-sm font-medium text-slate-500">Preview</p>
        <div className="rounded-3xl px-6 py-8 text-white" style={{ background: `linear-gradient(135deg, ${s.brand_color}, #0f172a)` }}>
          <div className="flex items-center gap-3">
            {s.logo_url ? <img src={imageSrc(s.logo_url)!} alt="" className="h-14 w-14 rounded-xl bg-white object-cover" />
              : <span className="flex h-14 w-14 items-center justify-center rounded-xl bg-white/20 text-xl font-bold">{s.name[0]}</span>}
            <div><p className="text-2xl font-bold">{s.name}</p><p className="text-white/80">{s.tagline}</p></div>
          </div>
          <p className="mt-4 text-sm text-white/80">{s.description}</p>
        </div>
      </div>
    </div>
  );
}

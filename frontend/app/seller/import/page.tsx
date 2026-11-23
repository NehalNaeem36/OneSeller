"use client";
import { useState } from "react";
import { api, ApiError, getToken, API_URL } from "@/lib/api";
import { Alert, Button, Card } from "@/components/ui";

interface Result { created: number; updated: number; failed: number; errors: { row: number; error: string }[] }

export default function ImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<Result | null>(null);
  const [err, setErr] = useState("");

  async function submit() {
    if (!file) return;
    setBusy(true); setErr(""); setRes(null);
    const fd = new FormData();
    fd.append("file", file);
    try { setRes(await api<Result>("/api/seller/products/import", { method: "POST", body: fd })); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "Import failed"); } finally { setBusy(false); }
  }

  async function template() {
    const r = await fetch(`${API_URL}/api/seller/products-import-template.csv`, { headers: { Authorization: `Bearer ${getToken()}` } });
    const url = URL.createObjectURL(await r.blob());
    const a = document.createElement("a"); a.href = url; a.download = "oneseller-products-template.csv"; a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-2xl font-semibold">Import products</h1>
      <Card className="space-y-4 p-6">
        <p className="text-sm text-slate-600">Upload a <strong>.csv</strong> or <strong>.xlsx</strong> file. Required columns: <code>name, category, price, stock</code>.
          Optional: <code>description, colors, sizes, sku</code> (colors/sizes comma-separated). Rows with an existing SKU update that product.</p>
        <button onClick={template} className="text-sm text-brand-600 hover:underline">Download CSV template</button>
        <input type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)}
          className="block w-full rounded-lg border border-dashed border-slate-300 p-4 text-sm" />
        <Button onClick={submit} disabled={!file} loading={busy}>Import</Button>
        {err && <Alert>{err}</Alert>}
        {res && (
          <div className="space-y-2">
            <Alert tone={res.failed ? "amber" : "green"}>Created {res.created}, updated {res.updated}, failed {res.failed}.</Alert>
            {res.errors.length > 0 && (
              <ul className="max-h-60 overflow-y-auto rounded-lg bg-slate-50 p-3 text-xs">
                {res.errors.map((e) => <li key={e.row}>Row {e.row}: {e.error}</li>)}
              </ul>)}
          </div>)}
      </Card>
    </div>
  );
}

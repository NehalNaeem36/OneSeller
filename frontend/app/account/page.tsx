"use client";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { User } from "@/lib/types";
import RequireRole from "@/components/RequireRole";
import { Alert, Button, Card, Input } from "@/components/ui";

const LABELS: Record<string, string> = { preferred_categories: "Preferred categories", preferred_colors: "Preferred colors",
  preferred_sizes: "Preferred sizes", budget_max: "Typical budget (Rs.)", notes: "Notes" };

function Inner() {
  const { user, setUser } = useAuth();
  const [f, setF] = useState({ full_name: user!.full_name, phone: user!.phone || "", address: user!.address || "",
    city: user!.city || "", postal_code: user!.postal_code || "" });
  const [mem, setMem] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<{ tone: "green" | "red"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { api<Record<string, string>>("/api/me/memory").then(setMem).catch(() => {}); }, []);

  async function save(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setMsg(null);
    try { setUser(await api<User>("/api/me", { method: "PUT", body: f })); setMsg({ tone: "green", text: "Profile saved." }); }
    catch (er) { setMsg({ tone: "red", text: er instanceof ApiError ? er.message : "Save failed" }); }
    finally { setBusy(false); }
  }
  async function forget(key?: string) {
    setMem(await api<Record<string, string>>("/api/me/memory", { method: "DELETE", query: { key } }));
  }

  return (
    <div className="mx-auto grid max-w-4xl gap-6 md:grid-cols-2">
      <Card className="p-6">
        <h1 className="text-lg font-semibold">Profile & delivery details</h1>
        <p className="mb-4 text-sm text-slate-500">{user!.email}</p>
        <form onSubmit={save} className="space-y-3">
          {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
          <Input label="Full name" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
          <Input label="Phone" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
          <Input label="Address" value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} />
          <div className="grid grid-cols-2 gap-3">
            <Input label="City" value={f.city} onChange={(e) => setF({ ...f, city: e.target.value })} />
            <Input label="Postal code" value={f.postal_code} onChange={(e) => setF({ ...f, postal_code: e.target.value })} />
          </div>
          <Button loading={busy}>Save</Button>
        </form>
      </Card>
      <Card className="p-6">
        <h2 className="text-lg font-semibold">What the AI remembers about you</h2>
        <p className="mb-4 text-sm text-slate-500">Long-term shopping preferences, used across conversations. Only non-sensitive preferences are stored — you can remove them anytime.</p>
        {Object.keys(mem).length === 0 ? <p className="text-sm text-slate-500">Nothing saved yet. Tell the assistant e.g. &ldquo;I usually wear size M&rdquo;.</p> : (
          <ul className="space-y-2">
            {Object.entries(mem).map(([k, v]) => (
              <li key={k} className="flex items-center justify-between rounded-lg bg-slate-50 px-3 py-2 text-sm">
                <span><span className="text-slate-500">{LABELS[k] || k}:</span> {v}</span>
                <button onClick={() => forget(k)} className="text-xs text-red-600 hover:underline">Remove</button>
              </li>))}
            <li><Button variant="secondary" size="sm" onClick={() => forget()}>Forget everything</Button></li>
          </ul>
        )}
      </Card>
    </div>
  );
}

export default function AccountPage() { return <RequireRole role="customer"><Inner /></RequireRole>; }

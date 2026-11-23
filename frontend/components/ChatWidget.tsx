"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { cx, uid } from "@/lib/format";
import type { ChatReply, ToolCall } from "@/lib/types";

interface Msg { role: "user" | "assistant"; content: string; tools?: ToolCall[] }

const SUGGESTIONS = ["Show me black shirts under Rs. 3000 in medium size", "Which one is cheaper?",
  "Recommend sneakers under Rs. 7000", "What's in my cart?"];

function load(key: string) { try { return localStorage.getItem(key); } catch { return null; } }
function save(key: string, v: string) { try { localStorage.setItem(key, v); } catch {} }

function Rich({ text }: { text: string }) {
  // Minimal, safe rendering: **bold** and line breaks only (no HTML injection).
  return (
    <div className="chat-md whitespace-pre-wrap">
      {text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? <strong key={i}>{part.slice(2, -2)}</strong> : <span key={i}>{part}</span>)}
    </div>
  );
}

export default function ChatWidget({ storeName }: { storeName?: string }) {
  const { user, refreshCart, ready } = useAuth();
  const [open, setOpen] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [threadId, setThreadId] = useState<string>("");
  const endRef = useRef<HTMLDivElement>(null);
  const customer = user?.role === "customer";
  const scope = customer ? `u${user!.id}` : "guest";

  useEffect(() => {
    if (!ready || user?.role === "seller") return;
    let t = load(`oneseller_thread_${scope}`);
    if (!t) { t = uid(); save(`oneseller_thread_${scope}`, t); }
    setThreadId(t);
    setMsgs([]);
    if (customer) {
      api<{ messages: Msg[] }>(`/api/chat/threads/${t}`).then((d) => setMsgs(d.messages)).catch(() => {});
    }
  }, [ready, scope, customer, user?.role]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy, open]);

  if (user?.role === "seller") return null;

  function guestId() {
    let g = load("oneseller_guest_id");
    if (!g) { g = "guest-" + uid(); save("oneseller_guest_id", g); }
    return g;
  }

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setInput("");
    setMsgs((m) => [...m, { role: "user", content: message }]);
    setBusy(true);
    try {
      const res = customer
        ? await api<ChatReply>("/api/chat", { method: "POST", body: { thread_id: threadId, message } })
        : await api<ChatReply>("/chat", { method: "POST", auth: false, body: { user_id: guestId(), thread_id: threadId, message } });
      setMsgs((m) => [...m, { role: "assistant", content: res.reply, tools: res.tool_calls }]);
      if (customer && res.tool_calls.some((c) => ["add_to_cart", "remove_from_cart", "create_order"].includes(c.name))) refreshCart();
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "Something went wrong.";
      setMsgs((m) => [...m, { role: "assistant", content: `⚠️ ${msg}` }]);
    } finally {
      setBusy(false);
    }
  }

  function newChat() {
    const t = uid();
    save(`oneseller_thread_${scope}`, t);
    setThreadId(t);
    setMsgs([]);
  }

  return (
    <>
      <button onClick={() => setOpen((o) => !o)} aria-label="Open AI assistant"
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-brand-600 px-5 py-3 font-medium text-white shadow-lg hover:bg-brand-700">
        <span className="text-lg">✦</span> {open ? "Close" : "Ask AI"}
      </button>
      {open && (
        <div className="fixed bottom-20 right-4 z-40 flex h-[70vh] max-h-[640px] w-[calc(100vw-2rem)] max-w-md flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
          <div className="flex items-center justify-between bg-brand-600 px-4 py-3 text-white">
            <div>
              <p className="font-semibold">OneSeller AI assistant</p>
              <p className="text-xs text-brand-100">{storeName ? `Helping you shop at ${storeName}` : "Search · compare · cart · checkout"}</p>
            </div>
            <button onClick={newChat} className="rounded-md bg-white/15 px-2 py-1 text-xs hover:bg-white/25">New chat</button>
          </div>
          <div className="flex-1 space-y-3 overflow-y-auto bg-slate-50 p-4 text-sm">
            {msgs.length === 0 && (
              <div className="space-y-3">
                <p className="text-slate-600">Hi! I can find products, compare prices, sizes and colors, manage your cart and place orders (only after you confirm).</p>
                {!customer && <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-800">You&apos;re browsing as a guest — <Link href="/login" className="underline">log in</Link> so the assistant can use your real cart and orders.</p>}
                <div className="flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => <button key={s} onClick={() => send(s)} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs hover:border-brand-500">{s}</button>)}
                </div>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={cx("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                <div className={cx("max-w-[85%] rounded-2xl px-3 py-2", m.role === "user" ? "bg-brand-600 text-white" : "border border-slate-200 bg-white")}>
                  <Rich text={m.content} />
                  {m.tools && m.tools.length > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1">
                      {m.tools.map((t, j) => (
                        <span key={j} title={JSON.stringify(t.args)} className={cx("rounded px-1.5 py-0.5 font-mono text-[10px]", t.ok === false ? "bg-red-50 text-red-700" : "bg-slate-100 text-slate-600")}>
                          ⚙ {t.name}
                        </span>))}
                    </div>
                  )}
                </div>
              </div>
            ))}
            {busy && <div className="flex gap-1 px-2 text-slate-400"><span className="animate-bounce">●</span><span className="animate-bounce [animation-delay:150ms]">●</span><span className="animate-bounce [animation-delay:300ms]">●</span></div>}
            <div ref={endRef} />
          </div>
          <form onSubmit={(e) => { e.preventDefault(); send(input); }} className="flex gap-2 border-t border-slate-200 p-3">
            <input value={input} onChange={(e) => setInput(e.target.value)} maxLength={2000} placeholder="Ask about products, sizes, your cart…"
              className="flex-1 rounded-full border border-slate-300 px-4 py-2 text-sm outline-none focus:border-brand-500" />
            <button disabled={busy || !input.trim()} className="rounded-full bg-brand-600 px-4 text-sm font-medium text-white disabled:opacity-50">Send</button>
          </form>
        </div>
      )}
    </>
  );
}

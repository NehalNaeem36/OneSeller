export type Role = "customer" | "seller";

export interface User {
  id: number; email: string; role: Role; full_name: string;
  phone?: string | null; address?: string | null; city?: string | null; postal_code?: string | null;
}

export interface StoreRef { id: number; name: string; slug: string; premium?: boolean }

export interface Product {
  id: number; name: string; description?: string | null; category: string; price: number; currency: string;
  colors: string[]; sizes: string[]; stock: number; in_stock: boolean; image_url?: string | null;
  store: StoreRef | null;
  sku?: string | null; is_active?: boolean; image_id?: number | null; deleted_at?: string | null; low_stock?: boolean;
}

export interface StoreCard {
  id: number; name: string; slug: string; tagline?: string | null; description?: string | null;
  brand_color: string; logo_url?: string | null; premium: boolean; product_count: number;
}

export interface CartLine {
  item_id: number; product_id: number; name: string; unit_price: number; quantity: number;
  color?: string | null; size?: string | null; subtotal: number; stock: number; available: boolean;
  image_url?: string | null; store: StoreRef;
}
export interface Cart { items: CartLine[]; total: number; item_count: number; currency: string; issues: string[] }

export interface OrderItem { product_id: number | null; name: string; unit_price: number; quantity: number;
  color?: string | null; size?: string | null; subtotal: number }
export interface Order {
  id: number; status: string; total: number; currency: string; payment_status: string; channel: string;
  is_sandbox: boolean; created_at: string; checkout_group: string; store: StoreRef | null; items: OrderItem[];
  delivery: { customer_name: string; phone: string; address: string; city: string; postal_code?: string | null };
}

export interface Subscription {
  plan: string; plan_name: string; status: "active" | "expired"; is_trial: boolean; period_start: string;
  period_end: string; days_remaining: number; order_limit: number; orders_used: number; simulation_enabled: boolean;
  plans: Record<string, { name: string; price: number; order_limit: number; features: string[] }>;
}

export interface ToolCall { name: string; args: Record<string, unknown>; agent?: string; ok?: boolean }
export interface ChatReply { reply: string; tool_calls: ToolCall[]; tokens: { in: number; out: number } }

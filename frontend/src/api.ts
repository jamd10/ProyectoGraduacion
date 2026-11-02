export async function api(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  const csrf = document.cookie
    .split("; ")
    .find((x) => x.startsWith("nexopass_csrf="))
    ?.split("=")[1];
  if (csrf) headers.set("X-CSRF-Token", decodeURIComponent(csrf));
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  const response = await fetch("/api/v1" + path, {
    ...options,
    headers,
    credentials: "include",
  });
  const value = await response
    .json()
    .catch(() => ({ detail: "El servidor no respondió correctamente" }));
  if (!response.ok)
    throw new Error(
      Array.isArray(value.detail)
        ? value.detail.map((v: any) => v.msg).join(". ")
        : value.detail || "No se pudo completar la operación",
    );
  return value;
}
export const post = (path: string, body?: unknown) =>
  api(path, {
    method: "POST",
    body: body === undefined ? undefined : JSON.stringify(body),
  });
export const patch = (path: string, body: unknown) =>
  api(path, { method: "PATCH", body: JSON.stringify(body) });
export const put = (path: string, body: unknown) =>
  api(path, { method: "PUT", body: JSON.stringify(body) });
export const remove = (path: string) => api(path, { method: "DELETE" });
export const money = (amount: any, currency = "HNL") =>
  new Intl.NumberFormat("es-HN", { style: "currency", currency }).format(
    Number(amount || 0),
  );
export const date = (value: string) =>
  new Intl.DateTimeFormat("es-HN", {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
export const labels: Record<string, string> = {
  active: "Activo",
  pending_mint: "Emitiendo NFT",
  used: "Utilizado",
  cancelled: "Cancelado",
  paid: "Pagada",
  pending_payment: "Pago pendiente",
  reversed: "Reversada",
  confirmed: "Confirmado",
  submitted: "En blockchain",
  queued: "En espera",
  failed: "Requiere revisión",
  invited: "Invitada",
  accepted: "Aceptada",
  expired: "Vencida",
  available: "Libre",
  reserved: "Reservado",
  sold: "Vendido",
  blocked: "Bloqueado",
  draft: "Borrador",
  published: "Publicado",
  finished: "Finalizado",
  denied: "Denegado",
  pending: "Pendiente",
};

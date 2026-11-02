import React, { createContext, useContext, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, LoaderCircle, Ticket, X } from "lucide-react";
import { api, labels } from "./api";
export const Session = createContext<any>(null);
export const useSession = () => useContext(Session);
export function Status({ value }: { value: string }) {
  return (
    <span className={"status status-" + value}>{labels[value] || value}</span>
  );
}
export function Empty({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <Ticket size={36} />
      <h2>{title}</h2>
      <div>{children}</div>
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading">
      <LoaderCircle className="spin" /> Un momento…
    </div>
  );
}
export function ErrorBox({ error }: { error: any }) {
  return error ? (
    <p role="alert" className="error">
      {String(error.message || error)}
    </p>
  ) : null;
}
export function Modal({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Cerrar">
            <X />
          </button>
        </div>
        {children}
      </section>
    </div>
  );
}
export function Field({ label, ...props }: any) {
  return (
    <label className="field">
      <span>{label}</span>
      <input {...props} />
    </label>
  );
}
export function Submit({ busy, children }: any) {
  return (
    <button className="button" disabled={busy} type="submit">
      {busy ? <LoaderCircle className="spin" size={18} /> : null}
      {children}
    </button>
  );
}
export function useLoad(path: string, interval = 0) {
  const [data, setData] = useState<any>(null),
    [error, setError] = useState<any>(null);
  useEffect(() => {
    let mounted = true;
    const load = () =>
      api(path)
        .then((x) => {
          if (mounted) {
            setData(x);
            setError(null);
          }
        })
        .catch((e) => {
          if (mounted) setError(e);
        });
    load();
    const timer = interval ? setInterval(load, interval) : undefined;
    return () => {
      mounted = false;
      clearInterval(timer);
    };
  }, [path, interval]);
  return { data, error, refresh: () => api(path).then(setData) };
}
export function Guard({
  children,
  admin = false,
}: {
  children: React.ReactNode;
  admin?: boolean;
}) {
  const { user, loading } = useSession();
  if (loading) return <Loading />;
  if (!user)
    return (
      <Empty title="Tu experiencia empieza aquí">
        <p>Inicia sesión para continuar.</p>
        <Link className="button" to="/login">
          Entrar <ArrowUpRight size={18} />
        </Link>
      </Empty>
    );
  if (admin && !user.roles.includes("admin"))
    return <Empty title="Esta sección es de administración" />;
  return <>{children}</>;
}

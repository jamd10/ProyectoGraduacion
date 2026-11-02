import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  QrCode,
  ShieldCheck,
  ArrowUpRight,
  Copy,
  RefreshCw,
  ArrowRightLeft,
} from "lucide-react";
import { api, post, date, money } from "../api";
import {
  useSession,
  useLoad,
  ErrorBox,
  Loading,
  Empty,
  Modal,
  Status,
  Field,
  Submit,
} from "../ui";

function QRModal({ ticket, onClose, guestToken }: any) {
  const [qr, setQr] = useState<any>(null),
    [error, setError] = useState<any>(null),
    [seconds, setSeconds] = useState(0);
  const load = () =>
    post(
      guestToken ? "/guest/qr" : "/tickets/" + ticket.id + "/qr",
      guestToken ? { token: guestToken } : undefined,
    )
      .then(setQr)
      .catch(setError);
  useEffect(() => {
    load();
    const timer = setInterval(load, 45000);
    return () => clearInterval(timer);
  }, [ticket.id, guestToken]);
  useEffect(() => {
    const timer = setInterval(
      () =>
        setSeconds(
          qr
            ? Math.max(
                0,
                Math.floor(
                  (new Date(qr.expires_at).getTime() - Date.now()) / 1000,
                ),
              )
            : 0,
        ),
      1000,
    );
    return () => clearInterval(timer);
  }, [qr]);
  return (
    <Modal title="Tu acceso al concierto" onClose={onClose}>
      <div className="qr-view">
        <span className="status status-active">
          <ShieldCheck size={15} /> NFT confirmado
        </span>
        <h3>{ticket.event_name}</h3>
        <p>{ticket.full_name}</p>
        <ErrorBox error={error} />
        {qr ? (
          <>
            <img src={qr.image} alt="Código QR temporal del boleto" />
            <p>El código se renueva automáticamente · {seconds} s</p>
            <button className="text-button" onClick={load}>
              <RefreshCw size={14} /> Renovar ahora
            </button>
            <button
              className="text-button"
              onClick={() =>
                navigator.clipboard.writeText(qr.token).catch(setError)
              }
            >
              <Copy size={14} /> Copiar código para lector manual
            </button>
          </>
        ) : (
          !error && <Loading />
        )}
        <p className="notice">
          Presenta tu documento original. El QR por sí solo no autoriza el
          ingreso.
        </p>
      </div>
    </Modal>
  );
}
function TicketCard({ ticket, onQR, onTransfer }: any) {
  return (
    <article className="ticket-card">
      <div className="ticket-top">
        <div>
          <span className="eyebrow">{ticket.zone_name}</span>
          <h2>{ticket.event_name}</h2>
          <p>{date(ticket.starts_at)}</p>
        </div>
        <Status value={ticket.suspended ? "Suspendido" : ticket.status} />
      </div>
      <div className="ticket-divider" />
      <div className="ticket-info">
        <div>
          <small>ASISTENTE</small>
          <strong>{ticket.full_name}</strong>
          <span>
            {ticket.document_type} · ••••{ticket.document_last_four}
          </span>
        </div>
        <div>
          <small>UBICACIÓN</small>
          <strong>
            {ticket.mode === "seated"
              ? `Fila ${ticket.row_label} · Asiento ${ticket.seat_label}`
              : "Admisión general"}
          </strong>
          <span>{money(ticket.unit_price, ticket.currency)}</span>
        </div>
      </div>
      <div className="ticket-actions">
        <button
          className="button small"
          disabled={ticket.status !== "active" || ticket.suspended}
          onClick={onQR}
        >
          <QrCode size={17} /> Abrir QR
        </button>
        {onTransfer && (
          <button
            className="button small secondary"
            disabled={
              ticket.status !== "active" ||
              ticket.transfer_count > 0 ||
              ticket.suspended
            }
            onClick={onTransfer}
          >
            <ArrowRightLeft size={16} /> Transferir
          </button>
        )}
      </div>
      <details className="nft-details">
        <summary>
          <ShieldCheck size={15} />{" "}
          {ticket.nft
            ? "Consultar autenticidad y trazabilidad"
            : "Emisión pendiente de confirmación"}
        </summary>
        {ticket.nft && (
          <>
            <p>Red de pruebas: {ticket.nft.chain_id}</p>
            <p>
              Contrato: <code>{ticket.nft.contract_address}</code>
            </p>
            <p>
              Token: <code>{ticket.nft.token_id}</code>
            </p>
            <p>
              Propietario: <code>{ticket.owner_address}</code>
            </p>
          </>
        )}
        {ticket.operations?.map((op: any, i: number) => (
          <div key={i}>
            <Status value={op.status} />
            <small>
              {op.kind === "mint"
                ? "Emisión"
                : op.kind === "transfer"
                  ? "Transferencia"
                  : "Ingreso"}{" "}
              {op.block_number ? "· bloque " + op.block_number : ""}
            </small>
            {op.tx_hash && <code>{op.tx_hash}</code>}
          </div>
        ))}
      </details>
    </article>
  );
}
export function Tickets() {
  const { data, error } = useLoad("/me/tickets", 3000),
    [qr, setQr] = useState<any>(null),
    [transfer, setTransfer] = useState<any>(null),
    [failure, setFailure] = useState<any>(null),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const invite = async (e: any) => {
    e.preventDefault();
    setBusy(true);
    try {
      const result = await post(
        "/tickets/" + transfer.id + "/transfers",
        Object.fromEntries(new FormData(e.currentTarget)),
      );
      setMessage(
        result.holder_authorized
          ? "Invitación enviada. El receptor debe aceptarla desde su cuenta."
          : "Se solicitó autorización al asistente actual y se invitó al receptor.",
      );
      setTransfer(null);
    } catch (e) {
      setFailure(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="page">
      <div className="section-head">
        <div>
          <span className="eyebrow">EXPERIENCIAS QUE SON TUYAS</span>
          <h1>
            Mis boletos<span className="accent">.</span>
          </h1>
        </div>
        <Link className="button secondary" to="/">
          Explorar conciertos <ArrowUpRight size={17} />
        </Link>
      </div>
      <ErrorBox error={error} />
      {message && (
        <div className="notice success">
          {message}
          <Link to="/transfers">Ver transferencias →</Link>
        </div>
      )}
      {!data && !error ? (
        <Loading />
      ) : data?.length === 0 ? (
        <Empty title="Aquí empieza tu colección de recuerdos">
          <p>Cuando compres, tus boletos aparecerán aquí.</p>
          <Link to="/">Encontrar mi próxima experiencia →</Link>
        </Empty>
      ) : (
        <div className="tickets-grid">
          {data?.map((ticket: any) => (
            <TicketCard
              key={ticket.id}
              ticket={ticket}
              onQR={() => setQr(ticket)}
              onTransfer={() => {
                setTransfer(ticket);
                setFailure(null);
              }}
            />
          ))}
        </div>
      )}
      {qr && (
        <QRModal
          ticket={data?.find((t: any) => t.id === qr.id) || qr}
          onClose={() => setQr(null)}
        />
      )}{" "}
      {transfer && (
        <Modal title="Transferir boleto" onClose={() => setTransfer(null)}>
          <p>
            Una transferencia por boleto, hasta 24 horas antes. Cambiará tanto
            el propietario del NFT como el asistente autorizado.
          </p>
          <form onSubmit={invite}>
            <Field
              label="Correo de la persona que lo recibirá"
              name="email"
              type="email"
              required
            />
            <ErrorBox error={failure} />
            <Submit busy={busy}>Enviar invitación</Submit>
          </form>
        </Modal>
      )}
    </section>
  );
}

export function Transfers() {
  const { user } = useSession(),
    { data, error, refresh } = useLoad("/me/transfers", 3000),
    [selected, setSelected] = useState<any>(null),
    [failure, setFailure] = useState<any>(null),
    [busy, setBusy] = useState(false);
  async function accept(e: any) {
    e.preventDefault();
    setBusy(true);
    try {
      await post(
        "/transfers/" + selected.id + "/accept",
        Object.fromEntries(new FormData(e.currentTarget)),
      );
      setSelected(null);
      refresh();
    } catch (e) {
      setFailure(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="page narrow">
      <span className="eyebrow">COMPARTE LA EXPERIENCIA</span>
      <h1>
        Transferencias<span className="accent">.</span>
      </h1>
      <p className="muted">
        El cambio de titular se completa cuando blockchain lo confirma.
      </p>
      <ErrorBox error={error} />
      {data?.length === 0 ? (
        <Empty title="No tienes invitaciones pendientes" />
      ) : (
        data?.map((t: any) => (
          <article className="panel" key={t.id}>
            <div className="section-head">
              <h2>{t.event_name}</h2>
              <Status value={t.status} />
            </div>
            <p>Destino: {t.recipient_email}</p>
            <p className="muted">Vence: {date(t.expires_at)}</p>
            {!t.holder_authorized_at && t.status === "invited" && (
              <p className="notice">
                Esperando autorización del asistente actual por correo.
              </p>
            )}
            {t.status === "invited" &&
              new Date(t.expires_at) > new Date() &&
              (t.recipient_email === user.email ? (
                <button
                  className="button"
                  disabled={!t.holder_authorized_at}
                  onClick={() => {
                    setSelected(t);
                    setFailure(null);
                  }}
                >
                  Aceptar boleto
                </button>
              ) : (
                <button
                  className="button secondary"
                  onClick={() =>
                    post("/transfers/" + t.id + "/cancel")
                      .then(refresh)
                      .catch(setFailure)
                  }
                >
                  Cancelar invitación
                </button>
              ))}
          </article>
        ))
      )}
      <ErrorBox error={failure} />
      {selected && (
        <Modal title="Acepta tu boleto" onClose={() => setSelected(null)}>
          <p>Escribe tus datos tal como aparecen en tu documento.</p>
          <form onSubmit={accept}>
            <Field
              label="Nombre completo"
              name="full_name"
              defaultValue={user.full_name}
              required
              minLength={2}
            />
            <Field
              label="Correo de tu cuenta"
              name="email"
              type="email"
              value={user.email}
              readOnly
            />
            <label className="field">
              <span>Documento</span>
              <select name="document_type">
                <option value="DNI">Identidad</option>
                <option value="PASSPORT">Pasaporte</option>
                <option value="OTHER">Otro autorizado</option>
              </select>
            </label>
            <Field
              label="Número de documento"
              name="document_number"
              minLength={4}
              required
            />
            <ErrorBox error={failure} />
            <Submit busy={busy}>Aceptar y solicitar transferencia</Submit>
          </form>
        </Modal>
      )}
    </section>
  );
}

export function GuestPage() {
  const [params] = useSearchParams(),
    token = params.get("token"),
    [ticket, setTicket] = useState<any>(null),
    [error, setError] = useState<any>(null),
    [qr, setQr] = useState(false);
  useEffect(() => {
    if (token) post("/guest/ticket", { token }).then(setTicket).catch(setError);
    else setError(new Error("Falta el enlace del boleto"));
  }, [token]);
  return (
    <section className="page narrow">
      <span className="eyebrow">TU INVITACIÓN AL MOMENTO</span>
      <h1>
        Tu boleto<span className="accent">.</span>
      </h1>
      <ErrorBox error={error} />
      {ticket ? (
        <TicketCard ticket={ticket} onQR={() => setQr(true)} />
      ) : (
        !error && <Loading />
      )}
      {qr && (
        <QRModal
          ticket={ticket}
          guestToken={token}
          onClose={() => setQr(false)}
        />
      )}
    </section>
  );
}
export function AuthorizeTransfer() {
  const [params] = useSearchParams(),
    [message, setMessage] = useState(""),
    [error, setError] = useState<any>(null);
  return (
    <section className="page narrow">
      <h1>Autorizar cambio de asistente</h1>
      <p>
        Continúa únicamente si aceptas que tu boleto pase a otra persona. La
        autorización no puede usarse dos veces.
      </p>
      {message ? (
        <p className="notice success">{message}</p>
      ) : (
        <button
          className="button"
          onClick={() =>
            post("/transfers/authorize", { token: params.get("token") })
              .then((x) => setMessage(x.message))
              .catch(setError)
          }
        >
          Autorizo la transferencia
        </button>
      )}
      <ErrorBox error={error} />
    </section>
  );
}

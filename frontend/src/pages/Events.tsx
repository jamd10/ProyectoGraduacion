import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowUpRight,
  MapPin,
  CalendarDays,
  ArrowLeft,
  ShieldCheck,
  Clock3,
  Search,
  Minus,
  Plus,
  Music2,
} from "lucide-react";
import { api, post, remove, money, date } from "../api";
import {
  useSession,
  useLoad,
  ErrorBox,
  Loading,
  Empty,
  Field,
  Submit,
} from "../ui";

function Poster({ event, index = 0 }: any) {
  return event.poster_url ? (
    <img
      className="event-poster"
      src={event.poster_url}
      alt={event.name}
      loading="lazy"
    />
  ) : (
    <div className={"poster-art poster-" + (index % 4)}>
      <span>
        NEXO
        <br />
        SESSIONS
      </span>
      <Music2 size={80} strokeWidth={0.8} />
      <small>{event.name}</small>
      <div className="poster-lines" />
    </div>
  );
}
export function Home() {
  const [search, setSearch] = useState(""),
    [city, setCity] = useState("");
  const { data, error } = useLoad(
    "/events?search=" +
      encodeURIComponent(search) +
      "&city=" +
      encodeURIComponent(city),
  );
  return (
    <>
      <section className="hero">
        <div className="hero-copy">
          <span className="eyebrow">
            <span className="live-dot" /> LA VIDA SUENA MEJOR EN VIVO
          </span>
          <h1>
            Tu próxima
            <br />
            <em>gran noche.</em>
          </h1>
          <p>
            La música que te mueve. El lugar que es tuyo.
            <br />
            Encuentra tu concierto y vive el momento.
          </p>
          <a href="#cartelera" className="button">
            Explorar conciertos <ArrowUpRight size={20} />
          </a>
          <div className="hero-proof">
            <ShieldCheck size={19} />
            <span>Boletos únicos, titularidad verificable.</span>
          </div>
        </div>
        <div className="hero-art" aria-hidden="true">
          <div className="vinyl">
            <div className="vinyl-label">
              nexo
              <br />
              <b>LIVE</b>
            </div>
          </div>
          <div className="floating-ticket">
            <span className="eyebrow">ALL ACCESS TO THE MOMENT</span>
            <strong>
              NOCHES
              <br />
              QUE CONECTAN.
            </strong>
            <div className="fake-bars" />
            <small>NEXOPASS / EXPERIENCIAS EN VIVO</small>
          </div>
          <span className="art-caption">EL MOMENTO ES AHORA ↗</span>
        </div>
      </section>
      <section className="promise-strip">
        <span>
          <ShieldCheck />
          NFT en red de pruebas
        </span>
        <span>
          <Clock3 />
          Tu lugar, reservado a tiempo
        </span>
        <span>
          <Music2 />
          Experiencias para recordar
        </span>
      </section>
      <section className="page" id="cartelera">
        <div className="section-head">
          <div>
            <span className="eyebrow">ENCUENTRA TU PRÓXIMO PLAN</span>
            <h2 className="section-title">
              En cartelera<span className="accent">.</span>
            </h2>
          </div>
          <span className="muted">{data?.length ?? 0} experiencias</span>
        </div>
        <div className="filters">
          <label className="search">
            <Search size={18} />
            <input
              aria-label="Buscar concierto"
              placeholder="Artista o concierto"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="search">
            <MapPin size={18} />
            <input
              aria-label="Filtrar por ciudad"
              placeholder="Todas las ciudades"
              value={city}
              onChange={(e) => setCity(e.target.value)}
            />
          </label>
        </div>
        <ErrorBox error={error} />
        {!data && !error ? (
          <Loading />
        ) : data?.length === 0 ? (
          <Empty title="Lo mejor está por anunciarse">
            <p>
              Pronto habrá nuevas experiencias. Si eres administrador, publica
              tu primer concierto desde el panel.
            </p>
          </Empty>
        ) : (
          <div className="event-grid">
            {data?.map((event: any, index: number) => (
              <Link
                className="event-card"
                to={"/events/" + event.id}
                key={event.id}
              >
                <div className="event-art">
                  <Poster event={event} index={index} />
                  <span className="event-kind">EN VIVO</span>
                  <span className="event-go">
                    <ArrowUpRight />
                  </span>
                </div>
                <small className="event-date">
                  <CalendarDays size={14} />
                  {date(event.starts_at)}
                </small>
                <h3>{event.name}</h3>
                <p>
                  <MapPin size={14} />
                  {event.venue_name} · {event.city}
                </p>
                <div className="event-card-bottom">
                  <span>Encuentra tu lugar</span>
                  <strong>Ver zonas ↗</strong>
                </div>
              </Link>
            ))}
          </div>
        )}
      </section>
      <section className="join-banner">
        <div>
          <span className="eyebrow">MENOS FILAS. MÁS RECUERDOS.</span>
          <h2>
            Tu entrada vive
            <br />
            contigo.
          </h2>
          <p>
            Una cuenta, tus boletos y un QR que se renueva.
            <br />
            Todo listo para cuando se apaguen las luces.
          </p>
        </div>
        <Link className="button light" to="/register">
          Crear mi cuenta <ArrowUpRight />
        </Link>
      </section>
    </>
  );
}

export function EventPage() {
  const { id } = useParams(),
    { user } = useSession(),
    navigate = useNavigate();
  const [event, setEvent] = useState<any>(null),
    [zone, setZone] = useState<any>(null),
    [seats, setSeats] = useState<any[]>([]),
    [selected, setSelected] = useState<string[]>([]),
    [quantity, setQuantity] = useState(1),
    [reservation, setReservation] = useState<any>(null),
    [method, setMethod] = useState("card_demo"),
    [busy, setBusy] = useState(false),
    [error, setError] = useState<any>(null),
    [scale, setScale] = useState(1),
    [remaining, setRemaining] = useState(0);
  async function reload() {
    const value = await api("/events/" + id);
    setEvent(value);
    if (zone) {
      const z = value.availability.zones.find((x: any) => x.id === zone.id);
      setZone(z);
      if (z?.mode === "seated") {
        const values = await api(`/events/${id}/zones/${z.id}/seats`);
        setSeats(values);
        setSelected((old) =>
          old.filter((x) =>
            values.some((s: any) => s.unit_id === x && s.can_select),
          ),
        );
      }
    }
  }
  useEffect(() => {
    reload().catch(setError);
    const timer = setInterval(() => {
      if (!reservation) reload().catch(setError);
    }, 5000);
    return () => clearInterval(timer);
  }, [id, zone?.id, reservation?.id]);
  useEffect(() => {
    if (!reservation) return;
    const update = () =>
      setRemaining(
        Math.max(
          0,
          Math.floor(
            (new Date(reservation.expires_at).getTime() - Date.now()) / 1000,
          ),
        ),
      );
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [reservation]);
  async function choose(value: any) {
    setZone(value);
    setSelected([]);
    setQuantity(1);
    setError(null);
    if (value.mode === "seated")
      try {
        setSeats(await api(`/events/${id}/zones/${value.id}/seats`));
      } catch (e) {
        setError(e);
      }
  }
  const count = zone?.mode === "seated" ? selected.length : quantity;
  async function reserve() {
    if (!user) {
      navigate("/login");
      return;
    }
    if (!user.verified) {
      navigate("/profile");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      setReservation(
        await post("/reservations", {
          event_id: id,
          zone_id: zone.id,
          unit_ids: zone.mode === "seated" ? selected : [],
          quantity,
        }),
      );
    } catch (e) {
      setError(e);
      reload().catch(() => {});
    } finally {
      setBusy(false);
    }
  }
  async function checkout(e: any) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const form = new FormData(e.currentTarget);
    const attendees = Array.from(
      { length: reservation.units.length },
      (_, i) => ({
        full_name: form.get("name" + i),
        email: form.get("email" + i),
        document_type: form.get("type" + i),
        document_number: form.get("doc" + i),
      }),
    );
    try {
      const result = await post(
        "/reservations/" + reservation.id + "/checkout",
        {
          idempotency_key:
            reservation.key ?? (reservation.key = crypto.randomUUID()),
          expected_total: reservation.total,
          attendees,
          method,
          result: form.get("result"),
          card_holder: form.get("card_holder") || "",
          card_number: form.get("card_number"),
          expiry: form.get("expiry") || "",
          cvv: form.get("cvv"),
        },
      );
      navigate(result.status === "pending_payment" ? "/profile" : "/tickets");
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  if (!event)
    return (
      <section className="page">
        <ErrorBox error={error} />
        {!error && <Loading />}
      </section>
    );
  return (
    <section className="page">
      <Link className="back-link" to="/">
        <ArrowLeft size={16} /> Volver a cartelera
      </Link>
      <div className="event-detail-head">
        <div className="event-detail-art">
          <Poster event={event} />
        </div>
        <div>
          <span className="eyebrow">UNA NOCHE PARA VIVIRLA</span>
          <h1>{event.name}</h1>
          <p>
            <CalendarDays size={17} />
            {date(event.starts_at)}
          </p>
          <p>
            <MapPin size={17} />
            {event.venue.name} · {event.venue.city}
          </p>
          <p className="muted">{event.description}</p>
          <span className="status status-active">
            Boleto nominativo · NFT en red de pruebas
          </span>
        </div>
      </div>
      <ErrorBox error={error} />
      {!reservation ? (
        <div className="booking-layout">
          <div>
            <div className="section-head">
              <h2>Encuentra tu lugar</h2>
              <small>Disponibilidad actualizada cada 5 segundos</small>
            </div>
            <div className="zones">
              {event.availability.zones.map((z: any) => (
                <button
                  className={
                    "zone-card " + (zone?.id === z.id ? "selected" : "")
                  }
                  key={z.id}
                  onClick={() => choose(z)}
                  disabled={!z.can_select}
                >
                  <div>
                    <strong>{z.name}</strong>
                    <small>
                      {z.mode === "seated"
                        ? "Asiento numerado"
                        : "Admisión general"}
                    </small>
                  </div>
                  <div>
                    <b>{money(z.price, z.currency)}</b>
                    <small>
                      {z.available} libres · {z.sold} vendidos · {z.reserved}{" "}
                      reservados
                    </small>
                  </div>
                </button>
              ))}
            </div>
            {zone?.image_url && (
              <img
                className="zone-image"
                src={zone.image_url}
                alt={"Ubicación de " + zone.name}
              />
            )}
            {zone?.mode === "seated" && (
              <div className="seat-map panel">
                <div className="map-toolbar">
                  <h3>{zone.name}</h3>
                  <label>
                    Zoom{" "}
                    <input
                      aria-label="Zoom del mapa"
                      type="range"
                      min="0.7"
                      max="1.6"
                      step="0.1"
                      value={scale}
                      onChange={(e) => setScale(Number(e.target.value))}
                    />
                  </label>
                </div>
                <div className="seat-scroll">
                  <div className="seat-content" style={{ zoom: scale }}>
                    <div className="stage">ESCENARIO</div>
                    {Array.from(new Set(seats.map((s) => s.row_label))).map(
                      (row) => (
                        <div className="seat-row" key={row}>
                          <span className="row-label">{row}</span>
                          {seats
                            .filter((s) => s.row_label === row)
                            .map((seat) => (
                              <button
                                key={seat.unit_id}
                                title={`Fila ${row}, asiento ${seat.seat_label}: ${seat.status}`}
                                aria-label={`Fila ${row}, asiento ${seat.seat_label}, ${seat.can_select ? "libre" : "no disponible"}`}
                                aria-pressed={selected.includes(seat.unit_id)}
                                disabled={!seat.can_select}
                                className={
                                  "seat " +
                                  seat.status +
                                  (selected.includes(seat.unit_id)
                                    ? " picked"
                                    : "")
                                }
                                onClick={() =>
                                  setSelected((old) =>
                                    old.includes(seat.unit_id)
                                      ? old.filter((x) => x !== seat.unit_id)
                                      : old.length < 6
                                        ? [...old, seat.unit_id]
                                        : old,
                                  )
                                }
                              >
                                {seat.seat_label}
                              </button>
                            ))}
                        </div>
                      ),
                    )}
                  </div>
                </div>
                <div className="legend">
                  <span>
                    <i className="available" />
                    Libre
                  </span>
                  <span>
                    <i className="picked" />
                    Tu selección
                  </span>
                  <span>
                    <i className="reserved" />
                    Reservado
                  </span>
                  <span>
                    <i className="sold" />
                    Vendido
                  </span>
                  <span>
                    <i className="blocked" />
                    Bloqueado
                  </span>
                </div>
              </div>
            )}
            {zone?.mode === "general" && (
              <div className="panel">
                <h3>¿Cuántas experiencias compartimos?</h3>
                <p className="muted">Esta zona no tiene asiento asignado.</p>
                <div className="quantity">
                  <button
                    aria-label="Quitar entrada"
                    onClick={() => setQuantity(Math.max(1, quantity - 1))}
                  >
                    <Minus />
                  </button>
                  <strong>{quantity}</strong>
                  <button
                    aria-label="Agregar entrada"
                    onClick={() =>
                      setQuantity(Math.min(6, zone.available, quantity + 1))
                    }
                  >
                    <Plus />
                  </button>
                </div>
              </div>
            )}
            {event.venue.seating_map_url && (
              <details className="panel">
                <summary>Ver plano de referencia del recinto</summary>
                <img
                  className="zone-image"
                  src={event.venue.seating_map_url}
                  alt="Plano de referencia del recinto"
                />
              </details>
            )}
          </div>
          <aside className="booking-summary panel">
            <span className="eyebrow">TU PRÓXIMA EXPERIENCIA</span>
            <h2>{event.name}</h2>
            <p>{zone?.name || "Elige una zona para comenzar"}</p>
            {zone?.benefits && <p className="muted">{zone.benefits}</p>}
            <div className="summary-line">
              <span>Boletos</span>
              <b>{zone ? count : 0}</b>
            </div>
            <div className="summary-line total">
              <span>Total</span>
              <b>
                {money(
                  zone ? Number(zone.price) * count : 0,
                  zone?.currency || "HNL",
                )}
              </b>
            </div>
            <button
              className="button full"
              disabled={!zone || !count || busy || !zone.can_select}
              onClick={reserve}
            >
              {busy ? "Reservando…" : "Continuar"}
              <ArrowUpRight size={18} />
            </button>
            <p className="fine-print">
              <Clock3 size={16} /> Tendrás 10 minutos para completar la compra.
            </p>
            <p className="fine-print">
              <ShieldCheck size={16} /> Cada boleto lleva el nombre y documento
              de su asistente.
            </p>
          </aside>
        </div>
      ) : (
        <form className="checkout-layout" onSubmit={checkout}>
          <div>
            <div className="section-head">
              <h2>¿Quiénes van contigo?</h2>
              <span className="status status-reserved">
                <Clock3 size={14} /> {Math.floor(remaining / 60)}:
                {String(remaining % 60).padStart(2, "0")}
              </span>
            </div>
            {reservation.units.map((unit: any, i: number) => (
              <div className="panel" key={unit.id}>
                <h3>
                  Boleto {i + 1} · {reservation.zone.name}
                  {unit.row_label
                    ? ` · Fila ${unit.row_label}, asiento ${unit.seat_label}`
                    : ""}
                </h3>
                <div className="form-grid">
                  <Field
                    label="Nombre completo del asistente"
                    name={"name" + i}
                    defaultValue={i === 0 ? user.full_name : ""}
                    required
                    minLength={2}
                  />
                  <Field
                    label="Correo del asistente"
                    name={"email" + i}
                    type="email"
                    defaultValue={i === 0 ? user.email : ""}
                    required
                  />
                  <label className="field">
                    <span>Documento</span>
                    <select name={"type" + i}>
                      <option value="DNI">Identidad</option>
                      <option value="PASSPORT">Pasaporte</option>
                      <option value="OTHER">Otro documento autorizado</option>
                    </select>
                  </label>
                  <Field
                    label="Número de documento"
                    name={"doc" + i}
                    required
                    minLength={4}
                    maxLength={40}
                  />
                </div>
              </div>
            ))}
            <div className="panel">
              <h2>Pago de demostración</h2>
              <p className="notice">
                No introduzcas tarjetas reales. No se realizará ningún cobro.
              </p>
              <div className="payment-methods">
                <button
                  type="button"
                  className={method === "card_demo" ? "selected" : ""}
                  onClick={() => setMethod("card_demo")}
                >
                  Tarjeta simulada
                </button>
                <button
                  type="button"
                  className={method === "crypto_demo" ? "selected" : ""}
                  onClick={() => setMethod("crypto_demo")}
                >
                  Cripto simulado
                </button>
              </div>
              {method === "card_demo" ? (
                <div className="form-grid">
                  <Field label="Titular ficticio" name="card_holder" required />
                  <Field
                    label="Número ficticio (13 a 19 dígitos)"
                    name="card_number"
                    required
                    inputMode="numeric"
                    pattern="[0-9 ]{13,23}"
                    autoComplete="off"
                  />
                  <Field
                    label="Vencimiento MM/AA"
                    name="expiry"
                    required
                    placeholder="12/30"
                    pattern="(0[1-9]|1[0-2])/[0-9]{2}"
                    autoComplete="off"
                  />
                  <Field
                    label="CVV ficticio"
                    name="cvv"
                    type="password"
                    inputMode="numeric"
                    required
                    pattern="[0-9]{3,4}"
                    maxLength={4}
                    autoComplete="off"
                  />
                </div>
              ) : (
                <p>
                  No necesitas criptomonedas ni conectar una extensión para esta
                  compra de demostración.
                </p>
              )}
              <label className="field">
                <span>Resultado del pago de demostración</span>
                <select name="result">
                  <option value="approved">Aprobar compra</option>
                  <option value="rejected">Probar rechazo</option>
                  <option value="pending">Probar pago pendiente</option>
                </select>
              </label>
            </div>
          </div>
          <aside className="booking-summary panel">
            <span className="eyebrow">RESUMEN</span>
            <h2>{event.name}</h2>
            <p>
              {reservation.units.length} boleto(s) · {reservation.zone.name}
            </p>
            <strong className="checkout-total">
              {money(reservation.total, reservation.zone.currency)}
            </strong>
            <p className="muted">
              La autenticidad del NFT se confirma después de emitirlo en
              blockchain.
            </p>
            <Submit busy={busy || remaining === 0}>
              Confirmar compra simulada
            </Submit>
            <button
              type="button"
              className="text-button"
              onClick={async () => {
                try {
                  await remove("/reservations/" + reservation.id);
                } catch {}
                setReservation(null);
                reload().catch(setError);
              }}
            >
              Volver y liberar mis lugares
            </button>
            <ErrorBox error={error} />
          </aside>
        </form>
      )}
    </section>
  );
}

import { useState } from "react";
import {
  Plus,
  ArrowLeft,
  Upload,
  LayoutDashboard,
  CalendarDays,
  Building2,
  Users,
  History,
  MapPin,
} from "lucide-react";
import { api, post, put, patch, remove, money, date } from "../api";
import {
  useLoad,
  ErrorBox,
  Modal,
  Field,
  Submit,
  Status,
  Loading,
} from "../ui";

const localDate = (value?: string) => {
  const d = value ? new Date(value) : new Date(Date.now() + 30 * 86400000);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);
};
function UploadImage({ target, id, onDone }: any) {
  const [error, setError] = useState<any>(null);
  return (
    <div className="upload-control">
      <label className="button small secondary">
        <Upload size={14} /> Subir imagen
        <input
          hidden
          type="file"
          accept="image/jpeg,image/png,image/webp"
          onChange={async (e) => {
            if (!e.target.files?.[0]) return;
            try {
              const body = new FormData();
              body.append("file", e.target.files[0]);
              await api("/images/" + target + "/" + id, {
                method: "POST",
                body,
              });
              onDone?.();
            } catch (e) {
              setError(e);
            }
          }}
        />
      </label>
      <ErrorBox error={error} />
    </div>
  );
}

export function Admin() {
  const [tab, setTab] = useState("dashboard"),
    [modal, setModal] = useState<any>(null),
    [selected, setSelected] = useState<any>(null),
    [error, setError] = useState<any>(null),
    [busy, setBusy] = useState(false);
  const events = useLoad("/admin/events"),
    venues = useLoad("/admin/venues"),
    dashboard = useLoad("/admin/dashboard", 5000),
    users = useLoad("/admin/users"),
    audit = useLoad("/admin/audit");
  const refresh = () => {
    events.refresh();
    venues.refresh();
    dashboard.refresh();
    audit.refresh();
  };
  async function submit(e: any) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const values: any = Object.fromEntries(new FormData(e.currentTarget));
    try {
      if (modal.kind === "venue") {
        modal.value
          ? await put("/admin/venues/" + modal.value.id, values)
          : await post("/admin/venues", values);
      } else {
        for (const field of [
          "starts_at",
          "ends_at",
          "doors_open_at",
          "sales_open_at",
          "sales_close_at",
          "transfer_deadline",
        ])
          values[field] = new Date(values[field]).toISOString();
        modal.value
          ? await put("/admin/events/" + modal.value.id, values)
          : await post("/admin/events", values);
      }
      setModal(null);
      refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  const menu = [
    ["dashboard", "Resumen", LayoutDashboard],
    ["events", "Conciertos", CalendarDays],
    ["venues", "Recintos", Building2],
    ["users", "Usuarios", Users],
    ["audit", "Trazabilidad", History],
  ] as const;
  return (
    <div className="admin-layout">
      <aside className="admin-sidebar">
        <span className="eyebrow">NEXO / CONTROL</span>
        <h2>Administración</h2>
        {menu.map(([id, label, Icon]) => (
          <button
            key={id}
            className={tab === id ? "active" : ""}
            onClick={() => {
              setTab(id);
              setSelected(null);
            }}
          >
            <Icon size={18} />
            {label}
          </button>
        ))}
      </aside>
      <section className="admin-main">
        <div className="section-head">
          <div>
            <span className="eyebrow">TODO BAJO CONTROL</span>
            <h1>
              {selected
                ? "Gestionar concierto"
                : menu.find((m) => m[0] === tab)?.[1]}
              <span className="accent">.</span>
            </h1>
          </div>
          {["events", "venues"].includes(tab) && !selected && (
            <button
              className="button"
              onClick={() => {
                setError(null);
                setModal({ kind: tab === "events" ? "event" : "venue" });
              }}
            >
              <Plus size={18} />
              Crear {tab === "events" ? "concierto" : "recinto"}
            </button>
          )}
        </div>
        <ErrorBox error={error} />
        {selected ? (
          <ManageEvent
            event={selected}
            onBack={() => {
              setSelected(null);
              refresh();
            }}
          />
        ) : tab === "dashboard" ? (
          <>
            <div className="stats">
              <div>
                <small>CONCIERTOS</small>
                <strong>{dashboard.data?.length ?? 0}</strong>
              </div>
              <div>
                <small>ÓRDENES PAGADAS</small>
                <strong>
                  {dashboard.data?.reduce(
                    (n: number, e: any) =>
                      n +
                      e.sales.reduce(
                        (v: number, s: any) => v + Number(s.orders),
                        0,
                      ),
                    0,
                  ) ?? 0}
                </strong>
              </div>
              <div>
                <small>BOLETOS REGISTRADOS</small>
                <strong>
                  {dashboard.data?.reduce(
                    (n: number, e: any) =>
                      n +
                      e.tickets.reduce(
                        (v: number, t: any) => v + Number(t.count),
                        0,
                      ),
                    0,
                  ) ?? 0}
                </strong>
              </div>
            </div>
            <h2>Ventas por concierto</h2>
            {dashboard.data?.map((e: any) => (
              <article className="panel" key={e.id}>
                <div className="section-head">
                  <h3>{e.name}</h3>
                  <Status value={e.status} />
                </div>
                {e.sales.length ? (
                  e.sales.map((sale: any) => (
                    <p key={sale.currency}>
                      {sale.orders} órdenes ·{" "}
                      <strong>{money(sale.total, sale.currency)}</strong>{" "}
                      simulados
                    </p>
                  ))
                ) : (
                  <p className="muted">Sin ventas confirmadas</p>
                )}
                <div className="chips">
                  {e.tickets.map((t: any) => (
                    <span key={t.status}>
                      <Status value={t.status} /> {t.count}
                    </span>
                  ))}
                </div>
              </article>
            ))}
          </>
        ) : tab === "events" ? (
          <>
            <ErrorBox error={events.error} />
            {events.data?.length === 0 && (
              <p className="notice">
                Crea un recinto, después el concierto y sus zonas.
              </p>
            )}
            {events.data?.map((e: any) => (
              <article className="admin-event panel" key={e.id}>
                <div>
                  <h2>{e.name}</h2>
                  <p>{date(e.starts_at)}</p>
                  <Status value={e.status} />
                </div>
                <div className="actions">
                  <button
                    className="button small"
                    onClick={() => setSelected(e)}
                  >
                    Zonas y personal
                  </button>
                  <button
                    className="button small secondary"
                    onClick={() => {
                      setError(null);
                      setModal({ kind: "event", value: e });
                    }}
                  >
                    Editar
                  </button>
                  {!["cancelled", "finished"].includes(e.status) && (
                    <button
                      className="button small danger"
                      onClick={() => {
                        if (
                          confirm(
                            "¿Cancelar este concierto? Se bloqueará el ingreso y se conservará el historial.",
                          )
                        )
                          post("/admin/events/" + e.id + "/cancel")
                            .then(refresh)
                            .catch(setError);
                      }}
                    >
                      Cancelar
                    </button>
                  )}
                </div>
                <UploadImage target="poster" id={e.id} onDone={refresh} />
              </article>
            ))}
          </>
        ) : tab === "venues" ? (
          <>
            {venues.data?.map((v: any) => (
              <article className="panel" key={v.id}>
                <div className="section-head">
                  <h2>{v.name}</h2>
                  <div className="actions">
                    <button
                      className="button small secondary"
                      onClick={() => setModal({ kind: "venue", value: v })}
                    >
                      Editar
                    </button>
                    <button
                      className="button small danger"
                      onClick={() => {
                        if (confirm("¿Eliminar este recinto sin conciertos?"))
                          remove("/admin/venues/" + v.id)
                            .then(refresh)
                            .catch(setError);
                      }}
                    >
                      Eliminar
                    </button>
                  </div>
                </div>
                <p>
                  <MapPin size={15} />
                  {v.city} · {v.address}
                </p>
                <div className="actions">
                  <div>
                    <small>Fotografía</small>
                    <UploadImage target="venue" id={v.id} onDone={refresh} />
                  </div>
                  <div>
                    <small>Plano de referencia</small>
                    <UploadImage target="map" id={v.id} onDone={refresh} />
                  </div>
                </div>
              </article>
            ))}
          </>
        ) : tab === "users" ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Persona</th>
                  <th>Correo</th>
                  <th>Estado</th>
                  <th>Acciones</th>
                </tr>
              </thead>
              <tbody>
                {users.data?.map((u: any) => (
                  <tr key={u.id}>
                    <td>{u.full_name}</td>
                    <td>{u.email}</td>
                    <td>
                      {u.disabled_at
                        ? "Deshabilitado"
                        : u.email_verified_at
                          ? "Verificado"
                          : "Sin verificar"}
                    </td>
                    <td>
                      <button
                        className="text-button"
                        onClick={() =>
                          patch("/admin/users/" + u.id + "/status", {
                            disabled: !u.disabled_at,
                          })
                            .then(users.refresh)
                            .catch(setError)
                        }
                      >
                        {u.disabled_at ? "Habilitar" : "Deshabilitar"}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Momento</th>
                  <th>Acción</th>
                  <th>Entidad</th>
                </tr>
              </thead>
              <tbody>
                {audit.data?.map((a: any) => (
                  <tr key={a.id}>
                    <td>{date(a.created_at)}</td>
                    <td>{a.action}</td>
                    <td>
                      {a.entity_type} · {a.entity_id.slice(0, 8)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {modal && (
          <Modal
            title={
              modal.kind === "venue"
                ? "Datos del recinto"
                : "Datos del concierto"
            }
            onClose={() => setModal(null)}
          >
            <form onSubmit={submit}>
              <Field
                label="Nombre"
                name="name"
                defaultValue={modal.value?.name}
                required
                minLength={2}
              />
              {modal.kind === "venue" ? (
                <>
                  <Field
                    label="Ciudad"
                    name="city"
                    defaultValue={modal.value?.city}
                    required
                  />
                  <Field
                    label="Dirección"
                    name="address"
                    defaultValue={modal.value?.address}
                    required
                  />
                  <Field
                    label="Zona horaria"
                    name="timezone"
                    defaultValue={
                      modal.value?.timezone || "America/Tegucigalpa"
                    }
                    required
                  />
                </>
              ) : (
                <>
                  <label className="field">
                    <span>Recinto</span>
                    <select
                      name="venue_id"
                      defaultValue={modal.value?.venue_id}
                      required
                    >
                      <option value="">Selecciona un recinto</option>
                      {venues.data?.map((v: any) => (
                        <option value={v.id} key={v.id}>
                          {v.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    <span>Descripción</span>
                    <textarea
                      name="description"
                      defaultValue={modal.value?.description}
                      minLength={5}
                      required
                    />
                  </label>
                  <div className="form-grid">
                    {[
                      ["starts_at", "Inicio"],
                      ["ends_at", "Finalización"],
                      ["doors_open_at", "Apertura de puertas"],
                      ["sales_open_at", "Inicio de venta"],
                      ["sales_close_at", "Cierre de venta"],
                      [
                        "transfer_deadline",
                        "Límite de transferencia (24 h antes)",
                      ],
                    ].map(([key, label]) => (
                      <Field
                        key={key}
                        type="datetime-local"
                        name={key}
                        label={label}
                        defaultValue={
                          modal.value ? localDate(modal.value[key]) : undefined
                        }
                        required
                      />
                    ))}
                  </div>
                  <label className="field">
                    <span>Publicación</span>
                    <select
                      name="status"
                      defaultValue={modal.value?.status || "draft"}
                    >
                      <option value="draft">Borrador</option>
                      <option value="published">Publicado</option>
                    </select>
                  </label>
                  <small>
                    Configura las zonas y revisa los horarios antes de publicar.
                  </small>
                </>
              )}
              <ErrorBox error={error} />
              <Submit busy={busy}>Guardar</Submit>
            </form>
          </Modal>
        )}
      </section>
    </div>
  );
}

function ManageEvent({ event, onBack }: any) {
  const { data, error, refresh } = useLoad(
      "/admin/events/" + event.id + "/zones",
    ),
    staff = useLoad("/admin/events/" + event.id + "/staff");
  const [modal, setModal] = useState<any>(null),
    [failure, setFailure] = useState<any>(null),
    [busy, setBusy] = useState(false),
    [seats, setSeats] = useState<any[] | null>(null),
    [selectedZone, setSelectedZone] = useState<any>(null);
  async function saveZone(e: any) {
    e.preventDefault();
    setBusy(true);
    setFailure(null);
    const body: any = Object.fromEntries(new FormData(e.currentTarget));
    try {
      if (modal.id) await put("/admin/zones/" + modal.id, body);
      else await post("/admin/events/" + event.id + "/zones", body);
      setModal(null);
      refresh();
    } catch (e) {
      setFailure(e);
    } finally {
      setBusy(false);
    }
  }
  async function showSeats(zone: any) {
    setSelectedZone(zone);
    try {
      setSeats(await api(`/admin/events/${event.id}/zones/${zone.id}/seats`));
    } catch (e) {
      setFailure(e);
    }
  }
  return (
    <>
      <button className="text-button" onClick={onBack}>
        <ArrowLeft size={16} /> Volver
      </button>
      <h2>{event.name}</h2>
      <ErrorBox error={error || failure} />
      <div className="section-head">
        <h3>Zonas e inventario</h3>
        <button
          className="button small"
          onClick={() => {
            setModal({});
            setFailure(null);
          }}
        >
          <Plus size={16} />
          Agregar zona
        </button>
      </div>
      {data?.zones.map((z: any) => (
        <article className="panel" key={z.id}>
          <div className="section-head">
            <h3>{z.name}</h3>
            <strong>{money(z.price, z.currency)}</strong>
          </div>
          <p>
            {z.capacity} lugares · {z.available} libres · {z.reserved}{" "}
            reservados · {z.sold} vendidos · {z.blocked} bloqueados
          </p>
          <div className="actions">
            <button
              className="button small secondary"
              onClick={() => {
                setModal(z);
                setFailure(null);
              }}
            >
              Editar
            </button>
            {z.mode === "seated" && (
              <button
                className="button small secondary"
                onClick={() => showSeats(z)}
              >
                Ver y bloquear asientos
              </button>
            )}
            <button
              className="button small danger"
              onClick={() => {
                if (confirm("¿Eliminar zona sin historial?"))
                  remove("/admin/zones/" + z.id)
                    .then(refresh)
                    .catch(setFailure);
              }}
            >
              Eliminar
            </button>
            <UploadImage target="zone" id={z.id} onDone={refresh} />
          </div>
        </article>
      ))}
      <div className="panel">
        <h3>Personal de acceso</h3>
        <form
          className="inline-form"
          onSubmit={async (e) => {
            e.preventDefault();
            const form = e.currentTarget;
            try {
              await post(
                "/admin/events/" + event.id + "/staff",
                Object.fromEntries(new FormData(form)),
              );
              staff.refresh();
              form.reset();
            } catch (e) {
              setFailure(e);
            }
          }}
        >
          <Field
            label="Correo de un usuario verificado"
            type="email"
            name="email"
            required
          />
          <Submit>Asignar</Submit>
        </form>
        {staff.data?.map((u: any) => (
          <div className="order-row" key={u.id}>
            <span>
              {u.full_name} · {u.email}
            </span>
            <button
              className="text-button"
              onClick={() =>
                remove(`/admin/events/${event.id}/staff/${u.id}`)
                  .then(staff.refresh)
                  .catch(setFailure)
              }
            >
              Retirar
            </button>
          </div>
        ))}
      </div>
      {modal && (
        <Modal
          title={modal.id ? "Editar zona" : "Nueva zona"}
          onClose={() => setModal(null)}
        >
          <form onSubmit={saveZone}>
            <Field
              label="Nombre comercial"
              name="name"
              defaultValue={modal.name}
              required
            />
            {!modal.id && (
              <>
                <label className="field">
                  <span>Modalidad</span>
                  <select name="mode">
                    <option value="seated">Asientos numerados</option>
                    <option value="general">Admisión general</option>
                  </select>
                </label>
                <div className="form-grid">
                  <Field
                    label="Capacidad"
                    name="capacity"
                    type="number"
                    min={1}
                    max={3000}
                    required
                  />
                  <Field
                    label="Asientos por fila"
                    name="seats_per_row"
                    type="number"
                    defaultValue={10}
                    min={1}
                    max={100}
                  />
                </div>
              </>
            )}
            <div className="form-grid">
              <Field
                label="Precio"
                name="price"
                type="number"
                step="0.01"
                min={0}
                defaultValue={modal.price}
                required
              />
              {!modal.id && (
                <Field
                  label="Moneda"
                  name="currency"
                  defaultValue="HNL"
                  required
                  maxLength={3}
                />
              )}
              <Field
                label="Orden visual"
                name="display_order"
                type="number"
                min={0}
                defaultValue={modal.display_order || 0}
              />
            </div>
            <Field
              label="Beneficios"
              name="benefits"
              defaultValue={modal.benefits || ""}
            />
            <ErrorBox error={failure} />
            <Submit busy={busy}>Guardar zona</Submit>
          </form>
        </Modal>
      )}
      {seats && (
        <Modal
          title={"Asientos · " + selectedZone.name}
          onClose={() => setSeats(null)}
        >
          <p>
            Haz clic para bloquear o habilitar un lugar libre. No se permite
            cambiar los reservados o vendidos.
          </p>
          <div className="admin-seats">
            {seats.map((s: any) => (
              <button
                key={s.unit_id}
                className={"seat " + s.status}
                disabled={["sold", "reserved"].includes(s.status)}
                title={`Fila ${s.row_label}, asiento ${s.seat_label}`}
                onClick={async () => {
                  try {
                    await patch("/admin/units/" + s.unit_id, {
                      enabled: !s.enabled,
                    });
                    await showSeats(selectedZone);
                    refresh();
                  } catch (e) {
                    setFailure(e);
                  }
                }}
              >
                {s.row_label}-{s.seat_label}
              </button>
            ))}
          </div>
          <ErrorBox error={failure} />
        </Modal>
      )}
    </>
  );
}

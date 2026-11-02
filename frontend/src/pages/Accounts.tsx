import { useState } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { ArrowUpRight, ShieldCheck, Mail, UserRound } from "lucide-react";
import { api, post, patch, date, money } from "../api";
import {
  useSession,
  Field,
  Submit,
  ErrorBox,
  useLoad,
  Status,
  Empty,
  Loading,
} from "../ui";

export function AuthPage() {
  const mode = useLocation().pathname.slice(1),
    [params] = useSearchParams(),
    navigate = useNavigate(),
    { refresh } = useSession();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState<any>(null),
    [message, setMessage] = useState("");
  const titles: any = {
    login: "Qué bueno verte.",
    register: "Tu próxima historia empieza aquí.",
    forgot: "Recupera tu acceso.",
    verify: "Confirma que eres tú.",
    reset: "Una nueva contraseña.",
  };
  async function submit(e: any) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const fields = Object.fromEntries(new FormData(e.currentTarget));
    try {
      if (mode === "login") {
        await post("/auth/login", fields);
        await refresh();
        navigate("/tickets");
      }
      if (mode === "register") {
        await post("/auth/register", fields);
        await post("/auth/login", {
          email: fields.email,
          password: fields.password,
        });
        await refresh();
        navigate("/profile");
      }
      if (mode === "forgot") {
        const result = await post("/auth/forgot", fields);
        setMessage(result.message);
      }
      if (mode === "verify") {
        const result = await post("/auth/verify", {
          token: params.get("token"),
        });
        await refresh();
        setMessage(result.message);
      }
      if (mode === "reset") {
        const result = await post("/auth/reset", {
          token: params.get("token"),
          password: fields.password,
        });
        await refresh();
        setMessage(result.message);
      }
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="auth-layout">
      <section className="auth-art">
        <span className="eyebrow">MÁS CERCA DE LO QUE TE MUEVE</span>
        <h1>
          Hay noches
          <br />
          que se quedan
          <br />
          <em>contigo.</em>
        </h1>
        <div className="orbit orbit-one" />
        <div className="orbit orbit-two" />
        <div className="auth-seal">
          <ShieldCheck />
          <span>
            Un boleto único.
            <br />
            Una experiencia tuya.
          </span>
        </div>
      </section>
      <section className="auth-form">
        <span className="eyebrow">BIENVENIDO A NEXOPASS</span>
        <h2>{titles[mode]}</h2>
        <p className="muted">
          {mode === "register"
            ? "Compra sin instalar una billetera. Nosotros nos encargamos del recorrido."
            : "Tus boletos y tus experiencias, en un solo lugar."}
        </p>
        <form onSubmit={submit}>
          {mode === "register" && (
            <Field
              label="Nombre completo"
              name="full_name"
              required
              minLength={2}
              autoComplete="name"
            />
          )}
          {["login", "register", "forgot"].includes(mode) && (
            <Field
              label="Correo electrónico"
              name="email"
              type="email"
              required
              autoComplete="email"
            />
          )}
          {["login", "register", "reset"].includes(mode) && (
            <Field
              label="Contraseña"
              name="password"
              type="password"
              minLength={mode === "login" ? 1 : 10}
              maxLength={128}
              required
              autoComplete={
                mode === "login" ? "current-password" : "new-password"
              }
            />
          )}
          {mode !== "login" && ["register", "reset"].includes(mode) && (
            <small>
              Mínimo 10 caracteres. No reutilices tu contraseña del trabajo.
            </small>
          )}
          <ErrorBox error={error} />
          {message ? (
            <div className="notice success">
              {message}
              <Link to="/login">Ir a mi cuenta →</Link>
            </div>
          ) : (
            <Submit busy={busy}>
              {mode === "login"
                ? "Entrar"
                : mode === "register"
                  ? "Crear mi cuenta"
                  : mode === "verify"
                    ? "Verificar correo"
                    : "Continuar"}{" "}
              <ArrowUpRight size={18} />
            </Submit>
          )}
        </form>
        <div className="auth-links">
          {mode === "login" ? (
            <>
              <Link to="/forgot">Olvidé mi contraseña</Link>
              <p>
                ¿Primera vez? <Link to="/register">Crea tu cuenta</Link>
              </p>
            </>
          ) : (
            <Link to="/login">Ya tengo una cuenta</Link>
          )}
        </div>
      </section>
    </div>
  );
}

export function Profile() {
  const { user, refresh } = useSession(),
    [error, setError] = useState<any>(null),
    [message, setMessage] = useState(""),
    [busy, setBusy] = useState(false);
  const orders = useLoad("/me/orders", 5000);
  const save = async (e: any) => {
    e.preventDefault();
    setBusy(true);
    try {
      const result = await patch(
        "/auth/me",
        Object.fromEntries(new FormData(e.currentTarget)),
      );
      setMessage(result.message);
      await refresh();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  const upload = async (e: any) => {
    if (!e.target.files[0]) return;
    try {
      const body = new FormData();
      body.append("file", e.target.files[0]);
      await api("/images/avatar/" + user.id, { method: "POST", body });
      await refresh();
    } catch (e) {
      setError(e);
    }
  };
  return (
    <section className="page narrow">
      <span className="eyebrow">TU ESPACIO</span>
      <h1>
        Mi perfil<span className="accent">.</span>
      </h1>
      <div className="profile-card">
        <label className="profile-avatar">
          {user.avatar_url ? (
            <img src={user.avatar_url} alt="Tu perfil" />
          ) : (
            <UserRound size={40} />
          )}
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp"
            onChange={upload}
          />
          <small>Cambiar foto</small>
        </label>
        <div>
          <h2>{user.full_name}</h2>
          <p>{user.email}</p>
          <span
            className={
              "status " + (user.verified ? "status-active" : "status-pending")
            }
          >
            {user.verified ? "Correo verificado" : "Verificación pendiente"}
          </span>
        </div>
      </div>
      {!user.verified && (
        <div className="notice">
          <Mail />
          <div>
            <strong>Un paso antes de comprar</strong>
            <p>
              Verifica tu correo. En la demostración puedes abrir tu bandeja
              privada.
            </p>
            <button
              className="button small secondary"
              onClick={() =>
                post("/auth/resend")
                  .then((x) => setMessage(x.message))
                  .catch(setError)
              }
            >
              Reenviar enlace
            </button>{" "}
            <Link className="button small" to="/mailbox">
              Abrir bandeja local
            </Link>
          </div>
        </div>
      )}
      <ErrorBox error={error} />
      {message && <p className="notice success">{message}</p>}
      <form className="panel" onSubmit={save}>
        <h2>Datos de tu cuenta</h2>
        <Field
          label="Nombre completo"
          name="full_name"
          defaultValue={user.full_name}
          required
          minLength={2}
        />
        <p className="muted">
          Cambiar el perfil no cambia el nombre de los boletos que ya compraste.
        </p>
        <Submit busy={busy}>Guardar cambios</Submit>
      </form>
      <div className="section-head">
        <h2>Mis compras</h2>
        <Link to="/mailbox">Bandeja de demostración →</Link>
      </div>
      <ErrorBox error={orders.error} />
      {orders.data?.length === 0 ? (
        <Empty title="Todavía no tienes compras">
          <Link to="/">Explorar conciertos</Link>
        </Empty>
      ) : (
        orders.data?.map((order: any) => (
          <div className="order-row" key={order.id}>
            <div>
              <strong>Orden {order.id.slice(0, 8)}</strong>
              <small>{date(order.created_at)}</small>
            </div>
            <Status value={order.status} />
            <strong>{money(order.total, order.currency)}</strong>
            {order.status === "pending_payment" && (
              <button
                className="button small"
                onClick={() =>
                  post("/orders/" + order.id + "/resolve-demo", {
                    result: "approved",
                  })
                    .then(orders.refresh)
                    .catch(setError)
                }
              >
                Aprobar pago simulado
              </button>
            )}
          </div>
        ))
      )}
    </section>
  );
}

export function Mailbox() {
  const { data, error } = useLoad("/me/mailbox", 5000);
  return (
    <section className="page narrow">
      <span className="eyebrow">SOLO PARA TU CUENTA</span>
      <h1>
        Bandeja local<span className="accent">.</span>
      </h1>
      <p className="muted">
        Correo de demostración, privado para tu usuario. Un envío SMTP se
        identifica con su estado.
      </p>
      <ErrorBox error={error} />
      {!data && !error ? (
        <Loading />
      ) : data?.length === 0 ? (
        <Empty title="Tu bandeja está al día" />
      ) : (
        data?.map((mail: any) => (
          <article className="mail panel" key={mail.id}>
            <div className="section-head">
              <h2>{mail.subject}</h2>
              <small>{date(mail.created_at)}</small>
            </div>
            <pre>
              {mail.body
                .split(/(https?:\/\/[^\s]+)/g)
                .map((text: string, i: number) =>
                  /^https?:\/\//.test(text) ? (
                    <a key={i} href={text}>
                      {text}
                    </a>
                  ) : (
                    text
                  ),
                )}
            </pre>
            <small>
              {mail.status === "local"
                ? "Entrega local de demostración"
                : mail.status === "sent"
                  ? "Enviado por SMTP"
                  : "Pendiente de envío"}
            </small>
          </article>
        ))
      )}
    </section>
  );
}

export function Help() {
  return (
    <section className="page narrow">
      <span className="eyebrow">SIN COMPLICACIONES</span>
      <h1>
        Tu boleto, paso a paso<span className="accent">.</span>
      </h1>
      <div className="help-grid">
        {[
          [
            "01",
            "Encuentra tu concierto",
            "Elige zona y asiento o cantidad. Los lugares se reservan por diez minutos mientras completas tu compra.",
          ],
          [
            "02",
            "Compra en modo demostración",
            "Usa datos de tarjeta ficticios o pago cripto simulado. No existen cargos reales. El NFT sí se emite en una blockchain de pruebas.",
          ],
          [
            "03",
            "Recibe tu boleto",
            "Cada asistente recibe su acceso por correo. Tu cuenta incluye una billetera custodiada de demostración: las claves se cifran en el servidor, no están bajo autocustodia.",
          ],
          [
            "04",
            "Entra con tu documento",
            "Abre el QR vigente y presenta el documento a nombre del boleto. El personal debe esperar la confirmación antes de autorizarte.",
          ],
        ].map(([n, title, text]) => (
          <article className="panel" key={n}>
            <span className="step-number">{n}</span>
            <h2>{title}</h2>
            <p>{text}</p>
          </article>
        ))}
      </div>
      <div className="notice">
        <ShieldCheck />
        <div>
          <strong>Transferencias con reglas claras</strong>
          <p>
            Una por boleto, hasta 24 horas antes del concierto. Requiere
            autorización del propietario y del asistente, más la aceptación de
            una cuenta verificada. El QR anterior queda inválido. Esto dificulta
            la reventa, pero no elimina pagos por fuera.
          </p>
        </div>
      </div>
      <p className="muted">
        Los nombres y documentos se mantienen fuera de la cadena pública. No se
        verifica identidad oficial en línea: el documento se comprueba
        presencialmente. Menores y casos especiales requieren revisión del
        organizador. El prototipo no procesa devoluciones bancarias reales ni
        verifica entradas sin conexión.
      </p>
      <p>
        Contacto del proyecto:{" "}
        <a href="mailto:nexopass@proton.me">nexopass@proton.me</a>
      </p>
    </section>
  );
}

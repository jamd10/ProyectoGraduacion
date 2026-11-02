import { useEffect, useState } from "react";
import {
  Routes,
  Route,
  NavLink,
  Link,
  useNavigate,
  useLocation,
} from "react-router-dom";
import {
  ArrowUpRight,
  Ticket,
  UserRound,
  ShieldCheck,
  ScanLine,
  LogOut,
  Menu,
  Radio,
} from "lucide-react";
import { api, post } from "./api";
import { Session, Guard } from "./ui";
import { Home, EventPage } from "./pages/Events";
import { AuthPage, Profile, Mailbox, Help } from "./pages/Accounts";
import {
  Tickets,
  Transfers,
  GuestPage,
  AuthorizeTransfer,
} from "./pages/Tickets";
import { Admin } from "./pages/Admin";
import { Access } from "./pages/Access";

export default function App() {
  const [user, setUser] = useState<any>(null),
    [loading, setLoading] = useState(true),
    [menu, setMenu] = useState(false);
  const navigate = useNavigate(),
    location = useLocation();
  const refresh = () =>
    api("/auth/me")
      .then(setUser)
      .catch(() => setUser(null));
  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, []);
  useEffect(() => {
    setMenu(false);
    window.scrollTo(0, 0);
  }, [location.pathname]);
  const logout = async () => {
    await post("/auth/logout");
    setUser(null);
    navigate("/");
  };
  return (
    <Session.Provider value={{ user, loading, refresh, setUser }}>
      <div className="top-note">
        <Radio size={12} /> PROTOTIPO DE GRADUACIÓN{" "}
        <span>Red de pruebas · pagos simulados</span>
      </div>
      <header className="header">
        <Link to="/" className="brand" aria-label="NexoPass inicio">
          <span className="brand-symbol">n</span>nexo<span>pass</span>
          <i />
        </Link>
        <button
          className="icon-btn mobile-menu"
          aria-label="Abrir navegación"
          onClick={() => setMenu(!menu)}
        >
          <Menu />
        </button>
        <nav className={menu ? "open" : ""}>
          <NavLink to="/" end>
            Explorar
          </NavLink>
          {user && (
            <>
              <NavLink to="/tickets">Mis boletos</NavLink>
              <NavLink to="/transfers">Transferencias</NavLink>
            </>
          )}
          <NavLink to="/help">Cómo funciona</NavLink>
        </nav>
        <div className="header-user">
          {user ? (
            <>
              <Link to="/profile" className="avatar" title={user.full_name}>
                {user.avatar_url ? (
                  <img src={user.avatar_url} alt="" />
                ) : (
                  <UserRound size={19} />
                )}
              </Link>
              {user.roles.includes("admin") && (
                <Link
                  className="icon-btn"
                  to="/admin"
                  aria-label="Administración"
                >
                  <ShieldCheck size={20} />
                </Link>
              )}
              {(user.roles.includes("admin") ||
                user.roles.includes("staff")) && (
                <Link
                  className="icon-btn"
                  to="/access"
                  aria-label="Control de acceso"
                >
                  <ScanLine size={20} />
                </Link>
              )}
              <button
                className="icon-btn"
                onClick={() => logout().catch(console.error)}
                aria-label="Cerrar sesión"
              >
                <LogOut size={18} />
              </button>
            </>
          ) : (
            <Link className="button small" to="/login">
              Entrar <ArrowUpRight size={16} />
            </Link>
          )}
        </div>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/events/:id" element={<EventPage />} />
          <Route path="/login" element={<AuthPage />} />
          <Route path="/register" element={<AuthPage />} />
          <Route path="/forgot" element={<AuthPage />} />
          <Route path="/verify" element={<AuthPage />} />
          <Route path="/reset" element={<AuthPage />} />
          <Route
            path="/profile"
            element={
              <Guard>
                <Profile />
              </Guard>
            }
          />
          <Route
            path="/mailbox"
            element={
              <Guard>
                <Mailbox />
              </Guard>
            }
          />
          <Route
            path="/tickets"
            element={
              <Guard>
                <Tickets />
              </Guard>
            }
          />
          <Route
            path="/transfers"
            element={
              <Guard>
                <Transfers />
              </Guard>
            }
          />
          <Route path="/guest" element={<GuestPage />} />
          <Route path="/authorize-transfer" element={<AuthorizeTransfer />} />
          <Route
            path="/admin"
            element={
              <Guard admin>
                <Admin />
              </Guard>
            }
          />
          <Route
            path="/access"
            element={
              <Guard>
                <Access />
              </Guard>
            }
          />
          <Route path="/help" element={<Help />} />
          <Route
            path="*"
            element={
              <section className="empty">
                <h1>Esta página no está en cartelera.</h1>
                <Link className="button" to="/">
                  Volver al inicio
                </Link>
              </section>
            }
          />
        </Routes>
      </main>
      <footer>
        <Link className="brand" to="/">
          nexo<span>pass</span>
        </Link>
        <p>Tu entrada. Tu experiencia.</p>
        <span>
          Prototipo académico. Sin cobros ni criptomonedas de valor real.
        </span>
      </footer>
    </Session.Provider>
  );
}

import { useEffect, useRef, useState } from "react";
import { Camera, ScanLine, ShieldCheck, XCircle } from "lucide-react";
import { api, post } from "../api";
import { useLoad, ErrorBox, Field, Loading } from "../ui";

export function Access() {
  const events = useLoad("/access/events"),
    [token, setToken] = useState(""),
    [check, setCheck] = useState<any>(null),
    [identity, setIdentity] = useState(false),
    [attempt, setAttempt] = useState<any>(null),
    [error, setError] = useState<any>(null),
    [busy, setBusy] = useState(false),
    [scanning, setScanning] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    if (!scanning) return;
    let stopped = false,
      controls: any;
    import("@zxing/browser")
      .then(async ({ BrowserQRCodeReader }) => {
        const reader = new BrowserQRCodeReader();
        controls = await reader.decodeFromVideoDevice(
          undefined,
          video.current!,
          (result, error, control) => {
            if (result) {
              setToken(result.getText());
              control.stop();
              setScanning(false);
            }
          },
        );
        if (stopped) controls.stop();
      })
      .catch((e) => {
        setError(
          new Error(
            "No se pudo abrir la cámara. Puedes pegar el código manualmente.",
          ),
        );
        setScanning(false);
      });
    return () => {
      stopped = true;
      controls?.stop();
    };
  }, [scanning]);
  useEffect(() => {
    if (!attempt || attempt.status !== "pending") return;
    const timer = setInterval(
      () =>
        api("/access/attempts/" + attempt.attempt_id)
          .then((value: any) => setAttempt({ ...value, attempt_id: value.id }))
          .catch(setError),
      1500,
    );
    return () => clearInterval(timer);
  }, [attempt?.attempt_id, attempt?.status]);
  async function inspect(e: any) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    setCheck(null);
    setAttempt(null);
    setIdentity(false);
    try {
      setCheck(await post("/access/check", { token: token.trim() }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  async function consume(matches: boolean) {
    setBusy(true);
    setError(null);
    try {
      setAttempt(
        await post("/access/consume", {
          token: token.trim(),
          identity_matches: matches,
        }),
      );
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="page narrow">
      <span className="eyebrow">PERSONAL AUTORIZADO</span>
      <h1>
        Control de acceso<span className="accent">.</span>
      </h1>
      <p className="muted">
        Confirma identidad y espera la respuesta final. Un QR válido no equivale
        a ingreso autorizado.
      </p>
      <ErrorBox error={events.error} />
      {events.data?.length === 0 ? (
        <p className="notice">
          No tienes conciertos asignados. Solicita la asignación a
          administración.
        </p>
      ) : (
        <p className="muted">
          Asignaciones: {events.data?.map((e: any) => e.name).join(" · ")}
        </p>
      )}
      <div className="panel">
        <button
          className="button secondary"
          disabled={!events.data?.length}
          onClick={() => setScanning(!scanning)}
        >
          <Camera size={18} />
          {scanning ? "Cerrar cámara" : "Escanear con cámara"}
        </button>
        {scanning && (
          <video ref={video} className="scanner-video" muted playsInline />
        )}
        <form onSubmit={inspect}>
          <Field
            label="Código QR leído o pegado manualmente"
            value={token}
            onChange={(e: any) => setToken(e.target.value)}
            required
            autoComplete="off"
          />
          <button className="button" disabled={busy || !events.data?.length}>
            <ScanLine size={18} /> Consultar boleto
          </button>
        </form>
      </div>
      <ErrorBox error={error} />
      {check && !attempt && (
        <div className="panel identity-card">
          <span className="eyebrow">COMPROBACIÓN PRESENCIAL</span>
          <h2>{check.full_name}</h2>
          <p>
            {check.document_type}: <strong>{check.document_number}</strong>
          </p>
          <p>{check.event}</p>
          <p className="notice">{check.message}</p>
          {!check.within_window && (
            <p className="error">
              Fuera del horario de ingreso. No puedes autorizar entrada.
            </p>
          )}
          <label className="checkbox">
            <input
              type="checkbox"
              checked={identity}
              onChange={(e) => setIdentity(e.target.checked)}
            />{" "}
            Comparé el documento original y coincide con esta persona.
          </label>
          <div className="actions">
            <button
              className="button"
              disabled={!identity || busy || !check.within_window}
              onClick={() => consume(true)}
            >
              Confirmar y esperar blockchain
            </button>
            <button
              className="button danger"
              disabled={busy}
              onClick={() => consume(false)}
            >
              El documento no coincide
            </button>
          </div>
        </div>
      )}
      {attempt && (
        <div
          className={
            "admission-result " +
            (attempt.authorized
              ? "success"
              : attempt.status === "pending"
                ? "waiting"
                : "denied")
          }
        >
          {attempt.authorized ? (
            <>
              <ShieldCheck size={64} />
              <h2>Entrada autorizada</h2>
              <p>El uso del boleto está confirmado.</p>
            </>
          ) : attempt.status === "pending" ? (
            <>
              <Loading />
              <h2>Esperando confirmación</h2>
              <p>Todavía NO autorices el ingreso.</p>
            </>
          ) : (
            <>
              <XCircle size={64} />
              <h2>Entrada no autorizada</h2>
              <p>
                {attempt.status === "denied"
                  ? "El documento no coincide."
                  : "La operación requiere revisión."}
              </p>
            </>
          )}
          <button
            className="button secondary"
            onClick={() => {
              setAttempt(null);
              setCheck(null);
              setToken("");
              setIdentity(false);
            }}
          >
            Consultar otro boleto
          </button>
        </div>
      )}
    </section>
  );
}

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import {
  api,
  type Connection,
  type ModelInfo,
  type ModelSettings,
} from "../api";
import { errorText, useI18n, type MessageKey } from "../i18n";
import { ask } from "../dialogs";

const PRESETS = [{ name: "Hubris", url: "https://api.hubris.pw/v1" }];

export default function Settings() {
  const { t } = useI18n();
  const [connections, setConnections] = useState<Connection[]>([]);
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [error, setError] = useState("");
  const [accounts, setAccounts] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);
  const navigate = useNavigate();

  const fail = useCallback((e: unknown) => setError(errorText(t, e)), [t]);
  const loadConnections = useCallback(
    () => api.connections().then(setConnections, fail),
    [fail],
  );
  useEffect(() => {
    loadConnections();
    api.settings().then(setSettings, fail);
    api.session().then((info) => {
      setAccounts(info.accounts);
      setIsAdmin(info.is_admin);
    }, fail);
  }, [loadConnections, fail]);

  const save = (patch: Partial<ModelSettings>) => {
    if (!settings) return;
    const next = { ...settings, ...patch };
    setSettings(next);
    api.saveSettings(next).catch(fail);
  };
  const remove = async (connection: Connection) => {
    if (!(await ask(t("settings.delete.confirm", { name: connection.name }))))
      return;
    await api.deleteConnection(connection.id).catch(fail);
    loadConnections();
    api.settings().then(setSettings, fail);
  };

  return (
    <main className="page narrow stack">
      <div className="row">
        <h1 className="grow">{t("settings.title")}</h1>
        <button
          className="btn ghost"
          title={t("settings.close")}
          aria-label={t("settings.close")}
          onClick={() =>
            window.history.length > 1 ? navigate(-1) : navigate("/")
          }
        >
          ✕
        </button>
      </div>
      {error && <p className="error">{error}</p>}

      {isAdmin && (
        <section className="panel pad stack">
          <div>
            <h2>{t("settings.connections")}</h2>
            <p className="muted">{t("settings.connections.hint")}</p>
          </div>
          {connections.length === 0 && (
            <p className="faint">{t("settings.connections.empty")}</p>
          )}
          {connections.map((connection) => (
            <div key={connection.id} className="row connection">
              <div className="grow">
                <b>{connection.name}</b>
                <div className="muted small">
                  {`${connection.base_url} · ${
                    connection.api_key_hint
                      ? t("settings.key.stored", {
                          hint: connection.api_key_hint,
                        })
                      : t("settings.key.none")
                  }`}
                </div>
              </div>
              <button
                className="btn ghost small danger"
                onClick={() => remove(connection)}
              >
                {t("app.delete")}
              </button>
            </div>
          ))}
          <AddConnection onAdded={loadConnections} />
        </section>
      )}

      {settings && (
        <section className="panel pad stack">
          <div>
            <h2>{t("settings.models")}</h2>
            <p className="muted">{t("settings.models.hint")}</p>
          </div>
          <ModelPicker
            title={t("settings.models.text")}
            kind="text"
            connections={connections}
            connectionId={settings.text_connection_id}
            model={settings.text_model}
            onChange={(connectionId, model) =>
              save({ text_connection_id: connectionId, text_model: model })
            }
          />
          <ModelPicker
            title={t("settings.models.image")}
            kind="image"
            connections={connections}
            connectionId={settings.image_connection_id}
            model={settings.image_model}
            onChange={(connectionId, model) =>
              save({ image_connection_id: connectionId, image_model: model })
            }
          />
          <ModelPicker
            title={t("settings.models.video")}
            kind="video"
            connections={connections}
            connectionId={settings.video_connection_id}
            model={settings.video_model}
            onChange={(connectionId, model) =>
              save({ video_connection_id: connectionId, video_model: model })
            }
          />
        </section>
      )}
      {accounts && <ChangePassword />}
    </main>
  );
}

function AddConnection({ onAdded }: { onAdded: () => void }) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");

  if (!open) {
    return (
      <div>
        <button className="btn" onClick={() => setOpen(true)}>
          + {t("settings.add")}
        </button>
      </div>
    );
  }
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      await api.createConnection({
        kind: "openai",
        name,
        base_url: url,
        api_key: key,
      });
      setOpen(false);
      setName("");
      setUrl("");
      setKey("");
      onAdded();
    } catch (e) {
      setError(errorText(t, e));
    }
  };
  return (
    <form className="stack subform" onSubmit={submit}>
      {
        <>
          <div className="row">
            {PRESETS.map((preset) => (
              <button
                key={preset.name}
                type="button"
                className="btn small"
                onClick={() => {
                  setName(preset.name);
                  setUrl(preset.url);
                }}
              >
                {preset.name}
              </button>
            ))}
          </div>
          <label className="field">
            {t("settings.url")}
            <input
              className="input"
              value={url}
              required
              placeholder="https://…/v1"
              onChange={(e) => setUrl(e.target.value)}
            />
          </label>
          <label className="field">
            {t("settings.key")}
            <input
              className="input"
              type="password"
              autoComplete="off"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
            <span className="faint">{t("settings.key.hint")}</span>
          </label>
        </>
      }
      <label className="field">
        {t("settings.name")}
        <input
          className="input"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </label>
      {error && <p className="error">{error}</p>}
      <div className="row">
        <button className="btn primary">{t("app.save")}</button>
        <button type="button" className="btn" onClick={() => setOpen(false)}>
          {t("app.cancel")}
        </button>
      </div>
    </form>
  );
}

interface PickerProps {
  title: string;
  kind: "text" | "image" | "video";
  connections: Connection[];
  connectionId: string;
  model: string;
  onChange: (connectionId: string, model: string) => void;
}

function ModelPicker({
  title,
  kind,
  connections,
  connectionId,
  model,
  onChange,
}: PickerProps) {
  const { t } = useI18n();
  const [models, setModels] = useState<ModelInfo[] | null>(null);
  const [freeOnly, setFreeOnly] = useState(false);
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState(false);
  const known = connections.some((c) => c.id === connectionId);

  useEffect(() => {
    setModels(null);
    setStatus("");
    if (!known) return;
    let stale = false;
    api.models(connectionId).then(
      (list) => !stale && setModels(list),
      (e) => {
        if (stale) return;
        setModels([]);
        setFailed(true);
        setStatus(errorText(t, e));
      },
    );
    return () => {
      stale = true;
    };
  }, [connectionId, known, t]);

  // A service that says what its models produce gets only the fitting ones offered:
  // text models for text, drawing models for pictures. One that does not shows them all.
  const kindsKnown = models?.some((m) => m.kind !== "unknown") ?? false;
  const anyPrice = models?.some((m) => m.free !== null) ?? false;
  const visible = (models ?? []).filter(
    (m) => (!kindsKnown || m.kind === kind) && (!freeOnly || m.free),
  );
  const test = async () => {
    setFailed(false);
    setStatus(t("settings.testing"));
    try {
      const result = await api.testModel(connectionId, model);
      setStatus(
        t("settings.test.ok", {
          reply: result.reply,
          input: result.input_tokens,
          output: result.output_tokens,
        }),
      );
    } catch (e) {
      setFailed(true);
      setStatus(errorText(t, e));
    }
  };

  return (
    <div className="stack subform">
      <h3>{title}</h3>
      <div className="row wrap">
        <label className="field grow">
          {t("settings.connection")}
          <select
            className="input"
            value={known ? connectionId : ""}
            onChange={(e) => onChange(e.target.value, "")}
          >
            <option value="">{t("settings.connection.none")}</option>
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="field grow">
          {t("settings.model")}
          <select
            className="input"
            value={model}
            disabled={!known || !models}
            onChange={(e) => onChange(connectionId, e.target.value)}
          >
            <option value="">
              {models || !known
                ? t("settings.model.none")
                : t("settings.models.loading")}
            </option>
            {/* Keep the saved model selectable even when a filter hides it. */}
            {model && !(models ?? []).some((m) => m.id === model) && (
              <option value={model}>{model}</option>
            )}
            {visible.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name === m.id ? m.id : `${m.name} (${m.id})`}
                {m.free ? ` · ${t("settings.free")}` : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      {known && models && (
        <div className="row wrap small muted">
          <span>{t("settings.models.count", { n: visible.length })}</span>
          {anyPrice && (
            <label className="row">
              <input
                type="checkbox"
                checked={freeOnly}
                onChange={(e) => setFreeOnly(e.target.checked)}
              />
              {t("settings.free.only")}
            </label>
          )}
          {models.length > 0 && !kindsKnown && (
            <span>{t("settings.kind.unknown")}</span>
          )}
          {kindsKnown && visible.length === 0 && (
            <span>{t(`settings.kind.none.${kind}` as MessageKey)}</span>
          )}
          <span className="spacer" />
          {/* Image models are exercised when the first picture is generated. */}
          {kind === "text" && (
            <button className="btn small" disabled={!model} onClick={test}>
              {t("settings.test")}
            </button>
          )}
        </div>
      )}
      {status && <p className={failed ? "error" : "ok"}>{status}</p>}
    </div>
  );
}

function ChangePassword() {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  return (
    <section className="panel pad row">
      <h2 className="grow">{t("settings.password.title")}</h2>
      <button className="btn" onClick={() => setOpen(true)}>
        {t("settings.password.submit")}
      </button>
      {open && <PasswordDialog onClose={() => setOpen(false)} />}
    </section>
  );
}

function PasswordDialog({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setMessage("");
    api.changePassword(current, next).then(
      () => {
        setCurrent("");
        setNext("");
        setMessage(t("settings.password.done"));
      },
      (e) => setError(errorText(t, e)),
    );
  };
  return (
    <div
      className="overlay"
      onMouseDown={(e) => e.target === e.currentTarget && onClose()}
    >
      <form className="dialog stack" onSubmit={submit}>
        <div className="row">
          <h2 className="grow">{t("settings.password.title")}</h2>
          <button
            type="button"
            className="btn ghost"
            aria-label={t("settings.close")}
            onClick={onClose}
          >
            ✕
          </button>
        </div>
        <label className="field">
          {t("settings.password.current")}
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
          />
        </label>
        <label className="field">
          {t("settings.password.new")}
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
          />
          <span className="faint">{t("auth.password.hint")}</span>
        </label>
        {error && <p className="error">{error}</p>}
        {message && <p className="notice">{message}</p>}
        <div className="row">
          <button className="btn primary" disabled={!current || !next}>
            {t("settings.password.submit")}
          </button>
        </div>
      </form>
    </div>
  );
}

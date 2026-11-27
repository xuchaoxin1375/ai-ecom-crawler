import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Button } from "../../components/ui/Button";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { Input } from "../../components/ui/Input";
import { loginWithKey } from "../../lib/api";

function safeNext(raw: string | null): string {
  if (!raw) return "/batches";
  let value = raw.trim();
  if (value.startsWith("/next/")) value = value.slice("/next/".length);
  if (value.startsWith("#")) value = value.slice(1);
  if (!value.startsWith("/") || value.startsWith("//")) return "/batches";
  return value;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = safeNext(searchParams.get("next"));
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) return;
    if (!key.trim()) {
      setError("请输入访问密钥");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await loginWithKey(key);
      navigate(next, { replace: true });
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10">
      <section className="w-full max-w-sm rounded-panel border border-line bg-surface p-6">
        <p className="text-xs font-medium tracking-wide text-ink-3">电商采集</p>
        <h1 className="mt-1 text-xl font-semibold text-ink">访问验证</h1>
        <p className="mt-2 text-sm leading-6 text-ink-2">
          用户名固定为 ecom；输入访问密钥即可继续。
        </p>
        <form className="mt-5 space-y-3" onSubmit={(event) => void submit(event)}>
          <div className="space-y-1.5">
            <label
              htmlFor="login-username"
              className="block text-sm font-medium text-ink"
            >
              用户名
            </label>
            <Input
              id="login-username"
              name="username"
              type="text"
              value="ecom"
              readOnly
              autoComplete="username"
              className="bg-surface-muted text-ink-2"
            />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="access-key" className="block text-sm font-medium text-ink">
              访问密钥
            </label>
            <Input
              id="access-key"
              name="password"
              type="password"
              autoComplete="current-password"
              value={key}
              aria-describedby={error ? "login-error" : undefined}
              onChange={(event) => setKey(event.target.value)}
            />
          </div>
          {error ? (
            <div id="login-error">
              <InlineNotice tone="danger">{error}</InlineNotice>
            </div>
          ) : null}
          <Button
            type="submit"
            variant="primary"
            className="w-full"
            disabled={submitting}
          >
            {submitting ? "正在验证…" : "进入"}
          </Button>
        </form>
        <p className="mt-4 text-xs leading-5 text-ink-3">
          用户名固定用于浏览器记住密码；访问密钥只保存哈希，HTTP 明文仅适合可信局域网。
        </p>
      </section>
    </main>
  );
}

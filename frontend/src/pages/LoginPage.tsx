import type { FormEvent } from "react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { AuthLayout, ErrorText, FieldLabel, inputClass, primaryButtonClass } from "../components/AuthLayout";
import { OAuthButtons } from "../components/OAuthButtons";
import { useAuth } from "../context/AuthContext";

type Mode = "password" | "otp-request" | "otp-verify";

export function LoginPage() {
  const { login, requestOtp, verifyOtp } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = searchParams.get("next") || "/";

  const [mode, setMode] = useState<Mode>("password");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handlePasswordLogin(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      navigate(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSendCode(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await requestOtp(email, "login");
      setMode("otp-verify");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerifyCode(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await verifyOtp(email, "login", code);
      navigate(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <AuthLayout
      title="Welcome back"
      subtitle="Sign in to see what Sentinel has found across your workspace."
      footer={
        <>
          Don't have an account?{" "}
          <Link to={`/signup?next=${encodeURIComponent(next)}`} className="font-medium text-ink underline underline-offset-2">
            Sign up
          </Link>
        </>
      }
    >
      <ErrorText>{error}</ErrorText>

      {mode === "password" && (
        <form onSubmit={handlePasswordLogin}>
          <div className="mb-4">
            <FieldLabel>Email</FieldLabel>
            <input
              required
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
              placeholder="you@company.com"
            />
          </div>
          <div className="mb-5">
            <FieldLabel>Password</FieldLabel>
            <input
              required
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
              placeholder="••••••••"
            />
          </div>
          <button type="submit" disabled={submitting} className={primaryButtonClass}>
            {submitting ? "Signing in…" : "Sign in"}
          </button>
          <button
            type="button"
            onClick={() => setMode("otp-request")}
            className="mt-3 w-full text-center text-small text-ink-dim underline underline-offset-2 hover:text-ink"
          >
            Use an email code instead
          </button>
        </form>
      )}

      {mode === "otp-request" && (
        <form onSubmit={handleSendCode}>
          <div className="mb-5">
            <FieldLabel>Email</FieldLabel>
            <input
              required
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
              placeholder="you@company.com"
            />
          </div>
          <button type="submit" disabled={submitting} className={primaryButtonClass}>
            {submitting ? "Sending…" : "Send login code"}
          </button>
          <button
            type="button"
            onClick={() => setMode("password")}
            className="mt-3 w-full text-center text-small text-ink-dim underline underline-offset-2 hover:text-ink"
          >
            Use a password instead
          </button>
        </form>
      )}

      {mode === "otp-verify" && (
        <form onSubmit={handleVerifyCode}>
          <p className="mb-4 text-small text-ink-dim">
            We sent a code to <b className="text-ink">{email}</b>. In dev mode without SMTP configured, check{" "}
            <code className="text-ink">docker compose logs backend</code> for it.
          </p>
          <div className="mb-5">
            <FieldLabel>Code</FieldLabel>
            <input
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className={inputClass}
              placeholder="000000"
              maxLength={10}
            />
          </div>
          <button type="submit" disabled={submitting} className={primaryButtonClass}>
            {submitting ? "Verifying…" : "Verify & sign in"}
          </button>
        </form>
      )}

      {mode !== "otp-verify" && <OAuthButtons />}
    </AuthLayout>
  );
}

import type { FormEvent } from "react";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { ApiError } from "../api/client";
import { AuthLayout, ErrorText, FieldLabel, inputClass, primaryButtonClass } from "../components/AuthLayout";
import { OAuthButtons } from "../components/OAuthButtons";
import { useAuth } from "../context/AuthContext";

export function SignupPage() {
  const { signup, verifyOtp } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const next = searchParams.get("next") || "/";

  const [step, setStep] = useState<"signup" | "verify">("signup");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSignup(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await signup(email, name, password);
      setStep("verify");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleVerify(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await verifyOtp(email, "email_verify", code);
      navigate(next);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setSubmitting(false);
    }
  }

  if (step === "verify") {
    return (
      <AuthLayout title="Check your email" subtitle={`We sent a verification code to ${email}.`}>
        <ErrorText>{error}</ErrorText>
        <form onSubmit={handleVerify}>
          <p className="mb-4 text-small text-ink-dim">
            No SMTP configured in this environment yet — read the code from{" "}
            <code className="text-ink">docker compose logs backend</code> instead of your inbox.
          </p>
          <div className="mb-5">
            <FieldLabel>Verification code</FieldLabel>
            <input
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
              className={inputClass}
              placeholder="000000"
              maxLength={10}
              autoFocus
            />
          </div>
          <button type="submit" disabled={submitting} className={primaryButtonClass}>
            {submitting ? "Verifying…" : "Verify & continue"}
          </button>
        </form>
      </AuthLayout>
    );
  }

  return (
    <AuthLayout
      title="Create your account"
      subtitle="One account, every workspace you belong to — starting with your own."
      footer={
        <>
          Already have an account?{" "}
          <Link to={`/login?next=${encodeURIComponent(next)}`} className="font-medium text-ink underline underline-offset-2">
            Sign in
          </Link>
        </>
      }
    >
      <ErrorText>{error}</ErrorText>
      <form onSubmit={handleSignup}>
        <div className="mb-4">
          <FieldLabel>Name</FieldLabel>
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={inputClass}
            placeholder="Your name"
          />
        </div>
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
            minLength={8}
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={inputClass}
            placeholder="At least 8 characters"
          />
        </div>
        <button type="submit" disabled={submitting} className={primaryButtonClass}>
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>
      <OAuthButtons />
    </AuthLayout>
  );
}

import { createFileRoute, Link, useRouter } from "@tanstack/react-router";
import { useState } from "react";

import { ButtonPrimary } from "@/components/sentinel/primitives";
import { useAuth } from "@/lib/auth";
import { AuthLayout, Field } from "./login";

export const Route = createFileRoute("/signup")({
  head: () => ({ meta: [{ title: "Create your account — Sentinel" }] }),
  component: SignupPage,
});

function SignupPage() {
  const { signup, verifyOtp } = useAuth();
  const router = useRouter();

  // Signup does not return a token: it mails a verification code, and that
  // code is what completes the account. So this is two steps, not one.
  const [step, setStep] = useState<"details" | "verify">("details");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title={step === "details" ? "Create your account" : "Check your email"}
      subtitle={
        step === "details"
          ? "One account, then connect the tools you already work in."
          : `We sent a 6-digit code to ${email}. Enter it to finish setting up.`
      }
      footer={
        <>
          Already have an account?{" "}
          <Link to="/login" className="text-ink underline underline-offset-2">
            Sign in
          </Link>
        </>
      }
    >
      {step === "details" ? (
        <>
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" className="input" />
          </Field>
          <Field label="Email">
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
              placeholder="you@company.com"
              className="input"
            />
          </Field>
          <Field label="Password">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              className="input"
            />
          </Field>

          {error && <p className="t-caption" style={{ color: "var(--crit)" }}>{error}</p>}

          <ButtonPrimary
            disabled={busy || !name || !email || password.length < 8}
            onClick={() =>
              void run(async () => {
                await signup(email, name, password);
                setStep("verify");
              })
            }
          >
            {busy ? "Creating…" : "Create account"}
          </ButtonPrimary>
          <p className="t-micro text-ink-faint">Password must be at least 8 characters.</p>
        </>
      ) : (
        <>
          <Field label="Verification code">
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              inputMode="numeric"
              placeholder="6-digit code"
              className="input font-mono tracking-[0.2em]"
            />
          </Field>

          {error && <p className="t-caption" style={{ color: "var(--crit)" }}>{error}</p>}

          <ButtonPrimary
            disabled={busy || code.length < 4}
            onClick={() =>
              void run(async () => {
                await verifyOtp(email, "email_verify", code);
                router.navigate({ to: "/" });
              })
            }
          >
            {busy ? "Verifying…" : "Verify and continue"}
          </ButtonPrimary>
        </>
      )}
    </AuthLayout>
  );
}

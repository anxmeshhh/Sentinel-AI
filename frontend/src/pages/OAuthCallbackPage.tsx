import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";

export function OAuthCallbackPage() {
  const { loginWithToken } = useAuth();
  const [status, setStatus] = useState<"working" | "done" | "error">("working");

  useEffect(() => {
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    if (!token) {
      setStatus("error");
      return;
    }
    loginWithToken(token)
      .then(() => setStatus("done"))
      .catch(() => setStatus("error"));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (status === "done") return <Navigate to="/" replace />;
  if (status === "error") return <Navigate to="/login" replace />;

  return (
    <div className="flex min-h-screen items-center justify-center bg-ground text-[13px] text-ink-dim">
      Signing you in&hellip;
    </div>
  );
}

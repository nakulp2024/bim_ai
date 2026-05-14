import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { setToken } from "../auth";

export function AuthCallbackPage() {
  const nav = useNavigate();
  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, "");
    const params = new URLSearchParams(hash);
    const t = params.get("token");
    if (t) {
      setToken(t);
      nav("/projects", { replace: true });
    } else {
      nav("/", { replace: true });
    }
  }, [nav]);
  return <div style={{ padding: 24 }}>Signing you in…</div>;
}

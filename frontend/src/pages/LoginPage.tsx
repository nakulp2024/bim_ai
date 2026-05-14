import { loginUrl } from "../api";

export function LoginPage() {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
        gap: 16,
      }}
    >
      <h1 style={{ margin: 0 }}>BIM AI</h1>
      <p style={{ color: "#888" }}>Sign in with your Speckle account to continue.</p>
      <a
        href={loginUrl()}
        style={{
          background: "#3a7",
          color: "#fff",
          padding: "10px 18px",
          borderRadius: 4,
          textDecoration: "none",
        }}
      >
        Sign in with Speckle
      </a>
    </div>
  );
}

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- App ---
    app_base_url: str = "http://localhost:5173"
    api_base_url: str = "http://localhost:8000"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    jwt_ttl_seconds: int = 60 * 60 * 24 * 7
    session_secret: str = "dev-only-change-me-too"

    # --- Database (our app DB, NOT Speckle's) ---
    database_url: str = "postgresql+asyncpg://bim:bim@app-postgres:5432/bim"

    # --- Speckle ---
    # The URL the BROWSER uses to reach Speckle (for OAuth redirects + viewer).
    speckle_public_url: str = "http://localhost:3000"
    # The URL the BACKEND uses to reach Speckle (server-to-server).
    speckle_internal_url: str = "http://speckle-server:3000"
    # Registered OAuth app credentials (created in Speckle UI; see README).
    speckle_app_id: str = ""
    speckle_app_secret: str = ""


settings = Settings()

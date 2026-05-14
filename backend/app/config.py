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
    # Sync URL used by Celery workers (no asyncpg).
    database_url_sync: str = "postgresql+psycopg2://bim:bim@app-postgres:5432/bim"

    # --- Redis / Celery (our app, separate from Speckle's Redis) ---
    redis_url: str = "redis://app-redis:6379/0"

    # --- Object storage / blob layout ---
    data_dir: str = "/data"

    # --- Speckle ---
    speckle_public_url: str = "http://localhost:3000"
    speckle_internal_url: str = "http://speckle-server:3000"
    speckle_app_id: str = ""
    speckle_app_secret: str = ""

    # --- Anthropic ---
    anthropic_api_key: str = ""
    claude_model: str = "claude-sonnet-4-6"


settings = Settings()

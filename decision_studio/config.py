from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Database
    database_url: str = "postgresql+asyncpg://decision_studio:decision_studio@localhost:5432/decision_studio"

    # LLM
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o"
    openai_api_key: str = ""
    openai_base_url: str = ""
    anthropic_api_key: str = ""

    # Embeddings (uses separate base URL since proxies often don't support embedding models)
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    embedding_api_key: str = ""
    embedding_base_url: str = ""

    # Search
    brave_search_api_key: str = ""

    # Intake
    #: Deployment-wide off switch, independent of the per-browser preference.
    #: With this false the questions endpoint returns an empty list without
    #: calling a model, and the client's own screen forwards straight to the
    #: analysis — so the feature can be turned off on a running deployment
    #: without rebuilding the frontend or asking users to change a setting.
    intake_enabled: bool = True
    #: Ceiling on the rendered answers. This string is prepended to *every*
    #: inference prompt, and a run evaluates hundreds of pairs, so the cost is
    #: roughly `chars/4 x pairs` extra input tokens — the number to weigh is
    #: that product, not the length of one answer. 6000 leaves ~1500 characters
    #: per question at the cap of four, which no sensible answer reaches.
    intake_context_max_chars: int = 6000
    #: Hard cap on questions. Four is a ceiling, not a target: the prompt is
    #: explicit that zero is a correct answer.
    intake_max_questions: int = 4

    # Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()

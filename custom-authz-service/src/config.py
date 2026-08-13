import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Unified Configuration settings for the Custom Authorization & Extension processor.
    """
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Ports (GRPC port defaults to PORT or 8080; health port defaults to HEALTH_PORT or 8081)
    PORT: int = int(os.getenv("PORT", "8080"))
    HEALTH_PORT: int = int(os.getenv("HEALTH_PORT", "8081"))

    # Apigee / External Authorization Target API Configuration
    TARGET_API_URL: str = os.getenv("TARGET_API_URL", "https://8.233.68.61.nip.io/custom-security")
    TARGET_API_KEY: str = os.getenv("TARGET_API_KEY", "")
    TARGET_API_TIMEOUT_SECONDS: float = float(os.getenv("TARGET_API_TIMEOUT_SECONDS", "2.0"))

    # Security & Gateway Policies
    FAIL_OPEN: bool = os.getenv("FAIL_OPEN", "false").lower() in ("true", "1", "yes")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    # Model Armor / Prompt Security Configuration
    ENABLE_PROMPT_INSPECTION: bool = os.getenv("ENABLE_PROMPT_INSPECTION", "true").lower() in ("true", "1", "yes")
    MAX_PROMPT_LENGTH: int = int(os.getenv("MAX_PROMPT_LENGTH", "100000"))

    # Agent Gateway Injected Response Headers
    HEADER_PRINCIPAL: str = os.getenv("HEADER_PRINCIPAL", "x-agentgateway-principal")
    HEADER_ALLOWED_TOOLS: str = os.getenv("HEADER_ALLOWED_TOOLS", "x-agentgateway-allowed-tools")
    HEADER_TENANT_ID: str = os.getenv("HEADER_TENANT_ID", "x-agentgateway-tenant-id")
    HEADER_SCOPES: str = os.getenv("HEADER_SCOPES", "x-agentgateway-scopes")
    HEADER_AUTH_STATUS: str = os.getenv("HEADER_AUTH_STATUS", "x-agentgateway-auth-status")

    # Ingress Gateway Reasoning Engine Routing Configuration
    GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "ai-practice-489716")
    REASONING_ENGINE_ID: str = os.getenv("REASONING_ENGINE_ID", "5756631115930533888")



settings = Settings()

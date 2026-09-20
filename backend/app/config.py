from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the M3-Cloud core services."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("M3CLOUD_ENVIRONMENT", "M3CLOUD_ENV"),
    )

    postgres_dsn: str = Field(
        default="postgresql+asyncpg://m3cloud:m3cloud@postgres:5432/m3cloud",
        validation_alias="M3CLOUD_POSTGRES_DSN",
    )
    redis_url: str = Field(
        default="redis://redis:6379/0",
        validation_alias="M3CLOUD_REDIS_URL",
    )

    minio_endpoint: str = Field(
        default="http://minio:9000",
        validation_alias="M3CLOUD_MINIO_ENDPOINT",
    )
    minio_access_key: str = Field(
        default="m3cloud",
        validation_alias="M3CLOUD_MINIO_ACCESS_KEY",
    )
    minio_secret_key: str = Field(
        default="change-me",
        validation_alias="M3CLOUD_MINIO_SECRET_KEY",
    )

    emqx_host: str = Field(
        default="emqx",
        validation_alias="M3CLOUD_EMQX_HOST",
    )
    emqx_port: int = Field(
        default=1883,
        validation_alias="M3CLOUD_EMQX_PORT",
    )

    dji_mqtt_enabled: bool = Field(
        default=False,
        validation_alias="M3CLOUD_DJI_MQTT_ENABLED",
    )
    dji_mqtt_client_id: str = Field(
        default="m3-cloud",
        validation_alias="M3CLOUD_DJI_MQTT_CLIENT_ID",
    )
    dji_mqtt_username: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_MQTT_USERNAME",
    )
    dji_mqtt_password: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_MQTT_PASSWORD",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

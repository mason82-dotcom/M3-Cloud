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

    s3_endpoint: str = Field(
        default="http://seaweedfs:8333",
        validation_alias=AliasChoices("M3CLOUD_S3_ENDPOINT", "M3CLOUD_MINIO_ENDPOINT"),
    )
    s3_access_key: str = Field(
        default="m3cloud",
        validation_alias=AliasChoices("M3CLOUD_S3_ACCESS_KEY", "M3CLOUD_MINIO_ACCESS_KEY"),
    )
    s3_secret_key: str = Field(
        default="change-me",
        validation_alias=AliasChoices("M3CLOUD_S3_SECRET_KEY", "M3CLOUD_MINIO_SECRET_KEY"),
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
    dji_control_api_token: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_CONTROL_API_TOKEN",
    )
    dji_telemetry_ttl_seconds: int = Field(
        default=15,
        validation_alias="M3CLOUD_DJI_TELEMETRY_TTL_SECONDS",
    )
    dji_state_cache_ttl_seconds: int = Field(
        default=86400,
        validation_alias="M3CLOUD_DJI_STATE_CACHE_TTL_SECONDS",
    )

    # DJI Pilot 2 DRC relay settings. The address must be reachable from the
    # RC Pro Enterprise and intentionally has no Docker-internal default.
    dji_drc_broker_address: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_DRC_BROKER_ADDRESS",
    )
    dji_drc_client_id_prefix: str = Field(
        default="m3cloud-drc-",
        validation_alias="M3CLOUD_DJI_DRC_CLIENT_ID_PREFIX",
    )
    dji_drc_username: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_DRC_USERNAME",
    )
    dji_drc_password: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_DRC_PASSWORD",
    )
    dji_drc_enable_tls: bool = Field(
        default=False,
        validation_alias="M3CLOUD_DJI_DRC_ENABLE_TLS",
    )
    dji_drc_credential_ttl_seconds: int = Field(
        default=3600,
        ge=1,
        validation_alias="M3CLOUD_DJI_DRC_CREDENTIAL_TTL_SECONDS",
    )
    dji_drc_osd_frequency_hz: int = Field(
        default=10,
        ge=1,
        le=30,
        validation_alias="M3CLOUD_DJI_DRC_OSD_FREQUENCY_HZ",
    )
    dji_drc_hsi_frequency_hz: int = Field(
        default=1,
        ge=1,
        le=30,
        validation_alias="M3CLOUD_DJI_DRC_HSI_FREQUENCY_HZ",
    )
    dji_drc_heartbeat_interval_seconds: float = Field(
        default=5.0,
        gt=0,
        validation_alias="M3CLOUD_DJI_DRC_HEARTBEAT_INTERVAL_SECONDS",
    )

    # DJI Pilot 2 H5 / JSBridge bootstrap. These URLs must be reachable from
    # the RC Pro Enterprise; Docker-internal hostnames such as "emqx" are not.
    dji_pilot_app_id: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_APP_ID",
    )
    dji_pilot_app_key: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_APP_KEY",
    )
    dji_pilot_license: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_LICENSE",
    )
    dji_pilot_workspace_id: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_WORKSPACE_ID",
    )
    dji_pilot_platform_name: str = Field(
        default="M3-Cloud",
        validation_alias="M3CLOUD_DJI_PILOT_PLATFORM_NAME",
    )
    dji_pilot_workspace_name: str = Field(
        default="M3-Cloud",
        validation_alias="M3CLOUD_DJI_PILOT_WORKSPACE_NAME",
    )
    dji_pilot_workspace_desc: str = Field(
        default="Self-hosted DJI Enterprise operations",
        validation_alias="M3CLOUD_DJI_PILOT_WORKSPACE_DESC",
    )
    dji_pilot_map_user_name: str = Field(
        default="M3-Cloud",
        validation_alias="M3CLOUD_DJI_PILOT_MAP_USER_NAME",
    )
    dji_pilot_map_element_prefix: str = Field(
        default="M3CLOUD",
        validation_alias="M3CLOUD_DJI_PILOT_MAP_ELEMENT_PREFIX",
    )
    dji_pilot_api_url: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_API_URL",
    )
    dji_pilot_api_token: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_API_TOKEN",
    )
    dji_pilot_mqtt_url: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_MQTT_URL",
    )
    dji_pilot_mqtt_username: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_MQTT_USERNAME",
    )
    dji_pilot_mqtt_password: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_MQTT_PASSWORD",
    )
    dji_pilot_ws_url: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_WS_URL",
    )
    dji_pilot_storage_endpoint: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_ENDPOINT",
    )
    dji_pilot_storage_sts_endpoint: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_STS_ENDPOINT",
    )
    dji_pilot_storage_provider: str = Field(
        default="minio",
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_PROVIDER",
    )
    dji_pilot_storage_region: str = Field(
        default="us-east-1",
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_REGION",
    )
    dji_pilot_storage_bucket: str = Field(
        default="m3-media",
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_BUCKET",
    )
    dji_pilot_storage_role_arn: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_ROLE_ARN",
    )
    dji_pilot_storage_sts_mode: str = Field(
        default="federation_token",
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_STS_MODE",
    )
    dji_pilot_storage_access_key: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_ACCESS_KEY",
    )
    dji_pilot_storage_secret_key: str = Field(
        default="",
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_SECRET_KEY",
    )
    dji_pilot_storage_sts_duration_seconds: int = Field(
        default=3600,
        validation_alias="M3CLOUD_DJI_PILOT_STORAGE_STS_DURATION_SECONDS",
    )
    dji_pilot_live_publish_type: str = Field(
        default="video-on-demand",
        validation_alias="M3CLOUD_DJI_PILOT_LIVE_PUBLISH_TYPE",
    )
    live_redis_channel: str = Field(
        default="m3:live",
        validation_alias="M3CLOUD_LIVE_REDIS_CHANNEL",
    )
    lyrebird_enabled: bool = Field(
        default=False,
        validation_alias="M3CLOUD_LYREBIRD_ENABLED",
    )
    lyrebird_hosts: str = Field(
        default="",
        validation_alias="M3CLOUD_LYREBIRD_HOSTS",
    )
    lyrebird_http_port: int = Field(
        default=8080,
        validation_alias="M3CLOUD_LYREBIRD_HTTP_PORT",
    )
    lyrebird_timeout_seconds: float = Field(
        default=1.5,
        validation_alias="M3CLOUD_LYREBIRD_TIMEOUT_SECONDS",
    )
    lyrebird_telemetry_port: int = Field(
        default=8081,
        validation_alias="M3CLOUD_LYREBIRD_TELEMETRY_PORT",
    )
    lyrebird_mavlink_port: int = Field(
        default=14550,
        validation_alias="M3CLOUD_LYREBIRD_MAVLINK_PORT",
    )
    lyrebird_mavlink_peer_port: int = Field(
        default=14550,
        validation_alias="M3CLOUD_LYREBIRD_MAVLINK_PEER_PORT",
    )
    lyrebird_mavlink_ttl_seconds: float = Field(
        default=5.0,
        validation_alias="M3CLOUD_LYREBIRD_MAVLINK_TTL_SECONDS",
    )
    mission_upload_enabled: bool = Field(
        default=False,
        validation_alias="M3CLOUD_MISSION_UPLOAD_ENABLED",
    )
    mission_upload_timeout_seconds: float = Field(
        default=6.0,
        validation_alias="M3CLOUD_MISSION_UPLOAD_TIMEOUT_SECONDS",
    )

    media_import_enabled: bool = Field(
        default=True,
        validation_alias="M3CLOUD_MEDIA_IMPORT_ENABLED",
    )
    media_import_root: str = Field(
        default="/media-import",
        validation_alias="M3CLOUD_MEDIA_IMPORT_ROOT",
    )
    media_import_scan_interval_seconds: float = Field(
        default=15.0,
        validation_alias="M3CLOUD_MEDIA_IMPORT_SCAN_INTERVAL_SECONDS",
    )
    media_import_min_age_seconds: float = Field(
        default=5.0,
        validation_alias="M3CLOUD_MEDIA_IMPORT_MIN_AGE_SECONDS",
    )
    media_filename_timezone: str = Field(
        default="UTC",
        validation_alias="M3CLOUD_MEDIA_FILENAME_TIMEZONE",
    )
    media_auto_match_flights: bool = Field(
        default=True,
        validation_alias="M3CLOUD_MEDIA_AUTO_MATCH_FLIGHTS",
    )
    media_auto_match_margin_seconds: float = Field(
        default=300.0,
        validation_alias="M3CLOUD_MEDIA_AUTO_MATCH_MARGIN_SECONDS",
    )
    media_auto_match_max_distance_m: float = Field(
        default=100.0,
        validation_alias="M3CLOUD_MEDIA_AUTO_MATCH_MAX_DISTANCE_M",
    )
    media_auto_match_min_gps_fraction: float = Field(
        default=0.8,
        validation_alias="M3CLOUD_MEDIA_AUTO_MATCH_MIN_GPS_FRACTION",
    )
    media_auto_match_max_gps_samples: int = Field(
        default=64,
        validation_alias="M3CLOUD_MEDIA_AUTO_MATCH_MAX_GPS_SAMPLES",
    )
    media_auto_match_max_sample_time_delta_seconds: float = Field(
        default=5.0,
        validation_alias="M3CLOUD_MEDIA_AUTO_MATCH_MAX_SAMPLE_TIME_DELTA_SECONDS",
    )
    media_import_handoff_root: str = Field(
        default="",
        validation_alias="M3CLOUD_MEDIA_IMPORT_HANDOFF_ROOT",
    )
    processing_import_root: str = Field(
        default="/processing-import",
        validation_alias="M3CLOUD_PROCESSING_IMPORT_ROOT",
    )
    processing_import_handoff_root: str = Field(
        default="",
        validation_alias="M3CLOUD_PROCESSING_IMPORT_HANDOFF_ROOT",
    )

    webodm_enabled: bool = Field(
        default=False,
        validation_alias="M3CLOUD_WEBODM_ENABLED",
    )
    webodm_url: str = Field(
        default="",
        validation_alias="M3CLOUD_WEBODM_URL",
    )
    webodm_token: str = Field(
        default="",
        validation_alias="M3CLOUD_WEBODM_TOKEN",
    )
    webodm_username: str = Field(
        default="",
        validation_alias="M3CLOUD_WEBODM_USERNAME",
    )
    webodm_password: str = Field(
        default="",
        validation_alias="M3CLOUD_WEBODM_PASSWORD",
    )
    webodm_timeout_seconds: float = Field(
        default=300.0,
        validation_alias="M3CLOUD_WEBODM_TIMEOUT_SECONDS",
    )
    processing_poll_interval_seconds: float = Field(
        default=5.0,
        validation_alias="M3CLOUD_PROCESSING_POLL_INTERVAL_SECONDS",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    hdc_dim: int = 10_000
    hdc_seed: int = 42
    clean_confidence_threshold: float = 0.95

    jev_api_key: str | None = None
    jev_base_url: str = "https://jevtypesafeai.com/api/v1/decide"
    jev_model: str = "jev-1.13.0"
    jev_timeout_ms: int = 400

    default_attachment: float = 40_000_000.0
    default_limit: float = 100_000_000.0
    default_copart: float = 0.90
    default_reinstatement_rate: float = 1.0
    default_reinstatements: int = 1
    default_layer_premium: float = 5_000_000.0

    audit_dir: str = "audit_logs"
    jobs_keep: int = 32

    google_maps_api_key: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.0-flash"
    flood_wse_m: float = 2.5
    open_buildings_path: str = ""
    open_buildings_url: str = ""
    default_shader_preset: str = "PHOTOREAL_DEFAULT"
    default_hazard_region: str = "nairobi"
    default_map_latitude: float = -1.28
    default_map_longitude: float = 36.82
    default_map_zoom: int = 12

    def model_post_init(self, __context) -> None:
        import os

        casters: dict[str, tuple[str, type]] = {
            "CATMOD_HDC_DIM": ("hdc_dim", int),
            "CATMOD_HDC_SEED": ("hdc_seed", int),
            "CATMOD_CLEAN_CONFIDENCE_THRESHOLD": ("clean_confidence_threshold", float),
            "JEV_API_KEY": ("jev_api_key", str),
            "JEV_BASE_URL": ("jev_base_url", str),
            "JEV_MODEL": ("jev_model", str),
            "JEV_TIMEOUT_MS": ("jev_timeout_ms", int),
            "CATMOD_DEFAULT_ATTACHMENT": ("default_attachment", float),
            "CATMOD_DEFAULT_LIMIT": ("default_limit", float),
            "CATMOD_DEFAULT_COPART": ("default_copart", float),
            "CATMOD_DEFAULT_REINSTATEMENT_RATE": ("default_reinstatement_rate", float),
            "CATMOD_DEFAULT_REINSTATEMENTS": ("default_reinstatements", int),
            "CATMOD_DEFAULT_LAYER_PREMIUM": ("default_layer_premium", float),
            "CATMOD_AUDIT_DIR": ("audit_dir", str),
            "GOOGLE_MAPS_API_KEY": ("google_maps_api_key", str),
            "GEMINI_API_KEY": ("gemini_api_key", str),
            "GEMINI_MODEL": ("gemini_model", str),
            "CATMOD_FLOOD_WSE_M": ("flood_wse_m", float),
            "OPEN_BUILDINGS_PATH": ("open_buildings_path", str),
            "OPEN_BUILDINGS_GEOJSON_URL": ("open_buildings_url", str),
            "CATMOD_SHADER_PRESET": ("default_shader_preset", str),
            "CATMOD_HAZARD_REGION": ("default_hazard_region", str),
            "CATMOD_MAP_LATITUDE": ("default_map_latitude", float),
            "CATMOD_MAP_LONGITUDE": ("default_map_longitude", float),
            "CATMOD_MAP_ZOOM": ("default_map_zoom", int),
        }
        for env_name, (attr, caster) in casters.items():
            raw = os.environ.get(env_name)
            if raw is None or raw == "":
                continue
            setattr(self, attr, caster(raw))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

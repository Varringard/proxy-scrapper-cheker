import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    APP_NAME: str = "ProxyPulse"
    VERSION: str = "1.0.0"
    
    # Web Dashboard and API
    WEB_HOST: str = os.getenv("WEB_HOST", "0.0.0.0")
    WEB_PORT: int = int(os.getenv("WEB_PORT", "8080"))
    
    # Built-in Rotating Proxy Gateway
    GATEWAY_ENABLED: bool = os.getenv("GATEWAY_ENABLED", "true").lower() in ("true", "1", "yes")
    GATEWAY_HOST: str = os.getenv("GATEWAY_HOST", "0.0.0.0")
    GATEWAY_PORT: int = int(os.getenv("GATEWAY_PORT", "8081"))
    GATEWAY_STRATEGY: str = os.getenv("GATEWAY_STRATEGY", "fastest")  # fastest, round-robin, random
    GATEWAY_COUNTRY: str = os.getenv("GATEWAY_COUNTRY", "")  # optional filter, e.g. "US"
    
    # Checker Engine
    CHECKER_CONCURRENCY: int = int(os.getenv("CHECKER_CONCURRENCY", "100"))
    CHECKER_TIMEOUT: float = float(os.getenv("CHECKER_TIMEOUT", "6.0"))
    CHECK_TARGET_URL: str = os.getenv("CHECK_TARGET_URL", "http://httpbin.org/ip")
    SSL_CHECK_URL: str = os.getenv("SSL_CHECK_URL", "https://api.ipify.org?format=json")
    
    # Periodic automation (seconds, 0 = disabled)
    AUTO_SCRAPE_INTERVAL: int = int(os.getenv("AUTO_SCRAPE_INTERVAL", "0"))
    AUTO_CHECK_INTERVAL: int = int(os.getenv("AUTO_CHECK_INTERVAL", "0"))
    
    # Storage
    DATA_DIR: str = os.getenv("DATA_DIR", "./data")
    DB_NAME: str = "proxies.db"
    
    @property
    def DB_PATH(self) -> str:
        os.makedirs(self.DATA_DIR, exist_ok=True)
        return os.path.join(self.DATA_DIR, self.DB_NAME)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()

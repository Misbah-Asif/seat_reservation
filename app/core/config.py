from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_uri: str
    # Applied to a new show when the request omits per_user_limit; the value is
    # then stored on the show, so changing this never affects existing shows.
    default_per_user_limit: int = Field(default=4, ge=1)

    # Connection pool. Caps how many requests talk to Postgres at once; the
    # rest wait in the pool queue (up to pool_timeout seconds) rather than fail.
    # pool_size + max_overflow must stay under the DB's max_connections.
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout: float = Field(default=30, gt=0)

settings = Settings()

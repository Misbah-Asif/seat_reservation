from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_uri: str
    # Applied to a new show when the request omits per_user_limit; the value is
    # then stored on the show, so changing this never affects existing shows.
    default_per_user_limit: int = Field(default=4, ge=1)

settings = Settings()

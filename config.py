from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:Altu78@localhost:5432/gymops"
    SECRET_KEY: str = "change-this-secret-key-in-production-min-32-chars!!"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    class Config:
        env_file = ".env"

settings = Settings()
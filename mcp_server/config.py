import os


class McpSettings:
    MCP_HOST: str = os.environ.get("MCP_HOST", "127.0.0.1")
    MCP_PORT: int = int(os.environ.get("MCP_PORT", "8200"))
    MCP_API_KEY: str = os.environ.get("MCP_API_KEY", "")

    MYSQL_USER: str = os.environ.get("MYSQL_USER", os.environ.get("DB_USER", "root"))
    MYSQL_PASSWORD: str = os.environ.get("MYSQL_PASSWORD", os.environ.get("DB_PASSWORD", ""))
    MYSQL_HOST: str = os.environ.get("MYSQL_HOST", os.environ.get("DB_HOST", "localhost"))
    MYSQL_PORT: str = os.environ.get("MYSQL_PORT", os.environ.get("DB_PORT", "3306"))
    MYSQL_DATABASE: str = os.environ.get("MYSQL_DATABASE", os.environ.get("DB_NAME", "coderunner"))

    @property
    def database_url(self) -> str:
        url = os.environ.get("DATABASE_URL")
        if url:
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            return url
        return (
            f"mysql+pymysql://{self.MYSQL_USER}:{self.MYSQL_PASSWORD}@"
            f"{self.MYSQL_HOST}:{self.MYSQL_PORT}/{self.MYSQL_DATABASE}"
            f"?charset=utf8mb4"
        )


def get_settings() -> McpSettings:
    return McpSettings()

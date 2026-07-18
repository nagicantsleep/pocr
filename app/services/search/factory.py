"""Search service construction shared by API reads and outbox projections."""

from app.config import get_settings
from app.services.search.embeddings import EmbeddingService
from app.services.search.repository import PostgresSearchRepository, SearchRepository
from app.services.search.service import SearchService


def build_search_service(repository: SearchRepository | None = None) -> SearchService:
    settings = get_settings()
    selected_repository = (
        PostgresSearchRepository()
        if settings.INVOICE_JP_DURABLE_MODE
        else repository or SearchRepository()
    )
    return SearchService(
        selected_repository,
        EmbeddingService(
            model=settings.SEARCH_EMBEDDING_MODEL,
            api_key=settings.SEARCH_EMBEDDING_API_KEY,
        ),
    )

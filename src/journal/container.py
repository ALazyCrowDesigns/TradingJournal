"""
Dependency Injection Container
Manages all application dependencies and their lifecycle
"""

from __future__ import annotations

import structlog
from dependency_injector import containers, providers
from sqlalchemy import Engine

from .config import settings
from .db.dao import _mk_engine
from .repositories.price import PriceRepository
from .repositories.symbol import SymbolRepository
from .repositories.trade import TradeRepository
from .services.analytics import AnalyticsService
from .services.backfill_service import BackfillService
from .services.cache import TTLCache
from .services.fundamentals import FundamentalsService
from .services.import_service import ImportService
from .services.market import MarketService


def configure_logging() -> None:
    """Configure structured logging"""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.render_to_log_kwargs,
            structlog.dev.ConsoleRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


class ApplicationContainer(containers.DeclarativeContainer):
    """Main DI container for the application"""

    # Configuration
    config = providers.Configuration()
    config.from_pydantic(settings)

    # Logging
    logging_setup = providers.Resource(configure_logging)

    # Core Infrastructure
    db_engine: providers.Provider[Engine] = providers.Singleton(
        _mk_engine,
    )

    # Caching
    cache = providers.Singleton(
        TTLCache,
        max_size=1000,  # Could be made configurable
        default_ttl=300,
    )

    # Repositories

    trade_repository = providers.Factory(
        TradeRepository,
        engine=db_engine,
        cache=cache,
    )

    symbol_repository = providers.Factory(
        SymbolRepository,
        engine=db_engine,
        cache=cache,
    )

    price_repository = providers.Factory(
        PriceRepository,
        engine=db_engine,
        cache=cache,
    )

    # Services

    market_service = providers.Singleton(
        MarketService,
        api_key=config.polygon_api_key,
        price_repository=price_repository,
        cache=cache,
    )

    fundamentals_service = providers.Singleton(
        FundamentalsService,
        api_key=config.fmp_api_key,
        symbol_repository=symbol_repository,
        cache=cache,
    )

    analytics_service = providers.Factory(
        AnalyticsService,
        trade_repository=trade_repository,
        price_repository=price_repository,
        cache=cache,
    )

    import_service = providers.Factory(
        ImportService,
        trade_repository=trade_repository,
        symbol_repository=symbol_repository,
        logger=providers.Factory(
            structlog.get_logger,
            name="import_service",
        ),
    )

    backfill_service = providers.Factory(
        BackfillService,
        trade_repository=trade_repository,
        price_repository=price_repository,
        market_service=market_service,
        logger=providers.Factory(
            structlog.get_logger,
            name="backfill_service",
        ),
    )


# Global container instance
container = ApplicationContainer()


def get_container() -> ApplicationContainer:
    """Get the global container instance"""
    return container

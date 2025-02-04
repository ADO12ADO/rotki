import abc
import json
import logging
from contextlib import suppress
from json import JSONDecodeError
from typing import Any, Final

from rotkehlchen.assets.asset import Asset, AssetWithOracles
from rotkehlchen.globaldb.cache import (
    globaldb_get_unique_cache_last_queried_ts_by_key,
    globaldb_get_unique_cache_value,
    globaldb_set_unique_cache_value,
)
from rotkehlchen.globaldb.handler import GlobalDBHandler
from rotkehlchen.logging import RotkehlchenLogsAdapter
from rotkehlchen.types import CacheType, Price, Timestamp
from rotkehlchen.utils.misc import ts_now
from rotkehlchen.utils.serialization import jsonloads_dict

logger = logging.getLogger(__name__)
log = RotkehlchenLogsAdapter(logger)


class CurrentPriceOracleInterface(metaclass=abc.ABCMeta):
    """
    Interface for oracles able to query current price. Oracle could be rate limited
    """

    def __init__(self, oracle_name: str) -> None:
        self.name = oracle_name

    @abc.abstractmethod
    def rate_limited_in_last(
            self,
            seconds: int | None = None,
    ) -> bool:
        """Denotes if the oracles has been rate limited in the last ``seconds``"""

    @abc.abstractmethod
    def query_current_price(
            self,
            from_asset: AssetWithOracles,
            to_asset: AssetWithOracles,
            match_main_currency: bool,
    ) -> tuple[Price, bool]:
        """
        Accepts a pair of assets to find price for and a flag. If `match_main_currency` is True
        and there is a manual latest price that has value in `main_currency`, then it will be
        returned without the conversion to `to_asset`.
        Returns:
        1. The price of from_asset at the current timestamp
        for the current oracle
        2. Whether returned price is in main currency
        """


class HistoricalPriceOracleInterface(CurrentPriceOracleInterface, metaclass=abc.ABCMeta):
    """Query prices for certain timestamps. Oracle could be rate limited"""

    @abc.abstractmethod
    def can_query_history(
            self,
            from_asset: Asset,
            to_asset: Asset,
            timestamp: Timestamp,
            seconds: int | None = None,
    ) -> bool:
        """Checks if it's okay to query historical price"""

    @abc.abstractmethod
    def query_historical_price(
            self,
            from_asset: Asset,
            to_asset: Asset,
            timestamp: Timestamp,
    ) -> Price:
        """An oracle implements this to return a historical price from_asset to to_asset at time.

        If no price can be found may raise:
        - PriceQueryUnsupportedAsset
        - NoPriceForGivenTimestamp
        - RemoteError
        """


class HistoricalPriceOracleWithCoinListInterface(HistoricalPriceOracleInterface, metaclass=abc.ABCMeta):  # noqa: E501
    """Historical Price Oracle with a cacheable list of all coins"""

    def __init__(self, oracle_name: str) -> None:
        super().__init__(oracle_name=oracle_name)

    def maybe_get_cached_coinlist(self, considered_recent_secs: int) -> dict[str, Any] | None:
        """Return the cached coinlist data if it exists in the DB cache and if it's recent"""
        now = ts_now()
        key_parts: Final = (CacheType.COINLIST, self.name)
        with GlobalDBHandler().conn.read_ctx() as cursor:
            last_ts = globaldb_get_unique_cache_last_queried_ts_by_key(cursor, key_parts)
            if abs(now - last_ts) <= considered_recent_secs:

                with suppress(JSONDecodeError):
                    return jsonloads_dict(globaldb_get_unique_cache_value(cursor, key_parts))  # type: ignore # due to the last_ts check get should return here

        return None

    def cache_coinlist(self, data: dict[str, Any]) -> None:
        with GlobalDBHandler().conn.write_ctx() as write_cursor:
            globaldb_set_unique_cache_value(
                write_cursor=write_cursor,
                key_parts=(CacheType.COINLIST, self.name),
                value=json.dumps(data),
            )

    @abc.abstractmethod
    def all_coins(self) -> dict[str, dict[str, Any]]:
        """Some historical price oracles (coingecko, cryptocompare) implement
        this to return all of their supported assets.

        May raise
        - RemoteError
        """

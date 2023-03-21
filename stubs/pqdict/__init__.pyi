from typing import TypeVar, Callable, Any, Iterable, Self, Iterator, Mapping
from collections.abc import MutableMapping

K = TypeVar("K")
V = TypeVar("V")

class pqdict(MutableMapping[K, V]):
    def __init__(
        self,
        data: Any = ...,
        key: Callable[[V], Any] | None = ...,
        reverse: bool = ...,
        precedes: Callable[[K, K], Any] = ...,
    ) -> None: ...
    @property
    def precedes(self) -> Callable[[K, K], Any]: ...
    @property
    def keyfn(self) -> Callable[[V], Any] | None: ...
    @classmethod
    def fromkeys(cls, iterable: Iterable[Any], value: Any, **kwargs: Any) -> Self: ...
    def __len__(self) -> int: ...
    def __contains__(self, key: object) -> bool: ...
    def __iter__(self) -> Iterator[K]: ...
    def __getitem__(self, key: K) -> V: ...
    def __setitem__(self, key: K, value: V) -> None: ...
    def __delitem__(self, key: K) -> None: ...
    def copy(self) -> Self: ...
    def top(self) -> K: ...
    def popitem(self) -> tuple[K, V]: ...
    def topitem(self) -> tuple[K, V]: ...
    def additem(self, key: K, value: V) -> None: ...
    def pushpopitem(self, key: K, value: V) -> tuple[K, V]: ...
    def updateitem(self, key: K, new_val: V) -> None: ...
    def replace_key(self, key: K, new_key: K) -> None: ...
    def swap_priority(self, key1: K, key2: K) -> None: ...
    def popkeys(self) -> Iterator[K]: ...
    def popvalues(self) -> Iterator[V]: ...
    def popitems(self) -> Iterator[tuple[K, V]]: ...
    def heapify(self, key: K = ...) -> None: ...
    def topvalue(self, default: V = ...) -> V: ...

PQDict = pqdict

def minpq(*args: Any, **kwargs: Any) -> pqdict[Any, Any]: ...
def maxpq(*args: Any, **kwargs: Any) -> pqdict[Any, Any]: ...
def nlargest(
    n: int, mapping: Mapping[K, V], key: Callable[[V], Any] | None = ...
) -> list[K]: ...
def nsmallest(
    n: int, mapping: Mapping[K, V], key: Callable[[V], Any] | None = ...
) -> list[K]: ...

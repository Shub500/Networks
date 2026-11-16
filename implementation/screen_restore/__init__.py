
from .engine import run_repair
from .incidence import repair as _pair_first
from .local import repair as _local_pair
from .local import ComponentFragmentIndex, LocalDeleteState
from .responses import ResponseStore
from .core import ChargedClock, SafeHistory, physical_components, quotient_load
from .pair_bags import pair_exchange, reverse_greedy

_ALGORITHM_OPTIONS = {
    "class_i": True,
    "class_ii": True,
    "max_same_component": 35,
    "rollout": True,
    "lazy": True,
    "history": True,
    "neutral": True,
    "response_cache": True,
    "bridge_bounds": True,
    "pair_priority": True,
    "splitter_priority": True,
    "profile_dedup": True,
    "cardinality_bounds": True,
    "slack_ties": True,
    "component_priority": True,
    "lazy_first_improvement": True,
    "cache_21_responses": True,
    "skip_certified_rollout_rg": True,
    "incremental_rollout_quotient": True,
    "grouped_history": True,
    "incident_rollout": True,
    "defer_unused_warmup": True,
    "direct_triple": True,
    "response_capacity": None,
    "history_limit_records": None,
    "history_limit_vertices": None,
    "neutral_strategy": "shed",
    "neutral_large_first": True,
    "neutral_max_trials": None,
    "neutral_descendant_lazy": True,
    "escape_order": "higher_first",
    "branch_unpruned_collection": False,
    "private_mass_history": True,
    "scalar_first": True,
    "batch_mode": "independent",
    "rescued_signatures": True,
    "batch_root_bounds": True,
    "batch_root_quota": None,
    "batch_stream_interval": 8,
    "batch_pack_limit": None,
    "defer_family_keys": True,
    "incremental_neutral_state": True,
    "localized_neutral_descendants": True,
}


def repair(adj, cap, deleted, seconds=10.0, *, clock=None):
    return run_repair(adj, cap, deleted, dict(_ALGORITHM_OPTIONS), seconds, clock)


def repair_local_pairs(adj, cap, deleted, seconds=30.0, *, clock=None):
    return _local_pair(adj, cap, deleted, seconds, clock=clock)


def repair_pair_first(adj, cap, deleted, seconds=30.0, *, clock=None):
    return _pair_first(adj, cap, deleted, seconds, fused=True, incremental=True, clock=clock)


__all__ = [
    "repair",
    "repair_local_pairs",
    "repair_pair_first",
    "pair_exchange",
    "reverse_greedy",
    "ComponentFragmentIndex",
    "LocalDeleteState",
    "ResponseStore",
    "ChargedClock",
    "SafeHistory",
    "physical_components",
    "quotient_load",
]

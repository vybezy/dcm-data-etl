"""dashboard stats"""

from repositories import stats_repository


def get_stats() -> dict:
    return stats_repository.get_counts()

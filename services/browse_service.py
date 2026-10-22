"""browse rules: masks patient names and raises NotFoundError for unknown parents."""

from repositories import browse_repository
from services.errors import NotFoundError


def mask_name(name: str) -> str:
    # the placeholder for removed names isn't personal data, so it stays readable
    if name == "ANONYMOUS":
        return name

    # "DOE^JOHN" -> "D** J***": first letter of each part stays, the rest is hidden
    parts = name.replace("^", " ").split()
    return " ".join(part[0] + "*" * (len(part) - 1) for part in parts)


def list_patients(limit: int, offset: int) -> list[dict]:
    patients = browse_repository.list_patients(limit, offset)
    for patient in patients:
        patient["patient_name"] = mask_name(patient["patient_name"])

    return patients


def list_studies(patient_id: int) -> list[dict]:
    if not browse_repository.patient_exists(patient_id):
        raise NotFoundError(f"patient {patient_id} not found")

    return browse_repository.list_studies(patient_id)


def list_series(study_id: int) -> list[dict]:
    if not browse_repository.study_exists(study_id):
        raise NotFoundError(f"study {study_id} not found")

    return browse_repository.list_series(study_id)


def list_instances(series_id: int) -> list[dict]:
    if not browse_repository.series_exists(series_id):
        raise NotFoundError(f"series {series_id} not found")

    return browse_repository.list_instances(series_id)

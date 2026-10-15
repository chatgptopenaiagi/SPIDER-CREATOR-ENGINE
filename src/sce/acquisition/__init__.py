"""Content-addressed evidence for explicitly selected local files/directories."""

from .local import AcquisitionPlan, LocalAcquirer, ResourceRecord

__all__ = ["AcquisitionPlan", "LocalAcquirer", "ResourceRecord"]

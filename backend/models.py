from pydantic import BaseModel
from typing import Optional


class FileRecord(BaseModel):
    id: int
    file_name: str
    file_name_no_ext: str
    extension: Optional[str]
    file_size: Optional[int]
    created_time: Optional[str]
    modified_time: Optional[str]
    file_path: str
    parent_dir: Optional[str]
    dir_depth: Optional[int]
    file_type: Optional[str]
    shapefile_group: Optional[str]
    disk_label: Optional[str]
    is_available: int = 1
    thumbnail_path: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class ScanLog(BaseModel):
    id: int
    scan_type: Optional[str]
    root_path: Optional[str]
    started_at: Optional[str]
    finished_at: Optional[str]
    total_files: Optional[int]
    added: int = 0
    deleted: int = 0
    modified: int = 0
    status: Optional[str]


class ScanStartRequest(BaseModel):
    root_path: str
    scan_type: str = "full"


class ConfigUpdateRequest(BaseModel):
    config: dict


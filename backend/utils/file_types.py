# 文件类型映射表（来自 PRD 4.5 节）

FILE_TYPE_MAP: dict[str, list[str]] = {
    "document": [
        ".doc", ".docx", ".pdf", ".txt", ".rtf", ".odt", ".wps",
    ],
    "spreadsheet": [
        ".xls", ".xlsx", ".csv", ".ods", ".et",
    ],
    "presentation": [
        ".ppt", ".pptx", ".odp", ".dps",
    ],
    "image": [
        ".jpg", ".jpeg", ".png", ".gif", ".bmp",
        ".webp", ".raw", ".cr2", ".nef", ".heic",
    ],
    "gis_vector": [
        # Shapefile 系列
        ".shp", ".shx", ".dbf", ".prj", ".cpg", ".sbn", ".sbx",
        # Geodatabase
        ".gdb", ".mdb",
        # 其他矢量格式
        ".gpkg", ".geojson",
        ".kml", ".kmz",
        # MapInfo
        ".tab", ".map", ".id",
        # ArcGIS 工程/图层文件
        ".mxd", ".aprx", ".lyr", ".lyrx",
        ".mpk", ".ppkx",
        # QGIS 工程文件
        ".qgs", ".qgz",
    ],
    "gis_raster": [
        ".tif", ".tiff", ".img",
        ".dem", ".adf",
        ".ecw", ".sid", ".jp2",
        ".nc", ".hdf", ".hdf5",
        ".msi",
    ],
    "mapgis": [
        ".mpj",
        ".wp", ".wl", ".wt",
        ".wat", ".mat",
        ".clr", ".lib",
    ],
    "fme": [
        ".fmw",
        ".fmwt",
        ".ffs",
    ],
    "cad": [
        ".dwg", ".dxf",
        ".dgn",
    ],
    "survey": [
        ".las", ".laz",
        ".e57",
        ".rinex",
        ".cor", ".obs",
    ],
    "archive": [
        ".zip", ".rar", ".7z", ".tar", ".gz",
    ],
    "other": [],
}

# 扩展名 → 类型 的反查字典
_EXT_TO_TYPE: dict[str, str] = {}
for _type, _exts in FILE_TYPE_MAP.items():
    for _ext in _exts:
        _EXT_TO_TYPE[_ext] = _type


def get_file_type(extension: str) -> str:
    """根据扩展名返回文件类型，未知扩展名返回 'other'。"""
    return _EXT_TO_TYPE.get(extension.lower(), "other")


# Shapefile 关联文件扩展名集合
SHAPEFILE_EXTENSIONS: frozenset[str] = frozenset({
    ".shp", ".shx", ".dbf", ".prj", ".cpg",
    ".sbn", ".sbx", ".xml",
})

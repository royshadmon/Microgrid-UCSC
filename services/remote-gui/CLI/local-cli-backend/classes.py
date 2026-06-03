
from pydantic import BaseModel
from typing import Dict


class Connection(BaseModel):
    conn: str


class DBConnection(BaseModel):
    dbms: str
    table: str

class Command(BaseModel):
    type: str # "GET" or "POST"
    cmd: str

class Policy(BaseModel):
    name: str  # Policy name
    data: Dict[str, str]  # Key-value pairs

class BookmarkUpdateRequest(BaseModel):
    node: str
    description: str

class PresetGroup(BaseModel):
    group_name: str

class PresetGroupID(BaseModel):
    group_id: str

class Preset(BaseModel):
    group_id: str
    group_name: str = "base"
    command: str
    type: str  # "GET" or "POST"
    button: str

class PresetID(BaseModel):
    preset_id: str

class DatabaseInfo(BaseModel):
    database: str

class TableInfo(BaseModel):
    database: str
    table: str

class ColumnInfo(BaseModel):
    database: str
    table: str

class SqlQuery(BaseModel):
    query: str


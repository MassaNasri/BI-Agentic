"""
Message Schema Validators for Kafka Topics
Ensures message structure consistency across the ETL pipeline
"""
from typing import Dict, Any, Optional, List, Tuple

from .db_type_utils import normalize_db_type


class MessageValidator:
    """
    Validates message schemas for each Kafka topic.
    Ensures data consistency and prevents pipeline errors.
    """
    
    @staticmethod
    def validate_connection_message(message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate connection_topic message structure.
        
        Expected structure:
        {
            "type": "file" | "database",
            "filename": str (if type="file"),
            "path": str (if type="file"),
            "size": int (if type="file"),
            "db_type": str (if type="database"),
            "host": str (if type="database"),
            "user": str (if type="database"),
            "password": str (if type="database"),
            "database": str (if type="database"),
            "port": int (if type="database")
        }
        """
        if "type" not in message:
            return False, "Missing 'type' field"
        
        if message["type"] not in ["file", "database"]:
            return False, f"Invalid type: {message['type']}"
        
        if message["type"] == "file":
            required = ["filename", "path", "size"]
            for field in required:
                if field not in message:
                    return False, f"Missing required field for file type: {field}"
        
        elif message["type"] == "database":
            required = ["db_type", "host", "user", "password", "database", "port"]
            for field in required:
                if field not in message:
                    return False, f"Missing required field for database type: {field}"
            if normalize_db_type(message.get("db_type")) is None:
                return False, "Unsupported db_type"
        
        return True, None
    
    @staticmethod
    def validate_schema_message(message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate schema_topic message structure.
        
        Expected structure:
        {
            "source": str,
            "type": "file" | "database",
            "columns": List[str],
            "dtypes": Dict[str, str],
            "row_count": int,
            "table": str (optional, for database sources)
        }
        """
        required = ["source", "type", "columns"]
        for field in required:
            if field not in message:
                return False, f"Missing required field: {field}"
        
        if not isinstance(message["columns"], list):
            return False, "Field 'columns' must be a list"
        
        if message["type"] not in ["file", "database"]:
            return False, f"Invalid type: {message['type']}"
        
        return True, None
    
    @staticmethod
    def validate_extracted_row_message(message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate extracted_rows_topic message structure.
        
        Expected structure:
        {
            "source": str,
            "row_id": int (optional, for file sources),
            "table": str (optional, for database sources),
            "data": Dict[str, Any]
        }
        """
        required = ["source", "data"]
        for field in required:
            if field not in message:
                return False, f"Missing required field: {field}"
        
        if not isinstance(message["data"], dict):
            return False, "Field 'data' must be a dictionary"
        
        return True, None
    
    @staticmethod
    def validate_clean_row_message(message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate clean_rows_topic message structure.
        
        Expected structure:
        {
            "source": str,
            "row_id": int (optional),
            "table": str (optional),
            "data": Dict[str, Any]
        }
        """
        required = ["source", "data"]
        for field in required:
            if field not in message:
                return False, f"Missing required field: {field}"
        
        if not isinstance(message["data"], dict):
            return False, "Field 'data' must be a dictionary"
        
        if not message["data"]:
            return False, "Field 'data' cannot be empty"
        
        return True, None
    
    @staticmethod
    def validate_load_status_message(message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate load_rows_topic message structure.
        
        Expected structure:
        {
            "source": str,
            "table": str,
            "status": "success" | "error",
            "row_count": int (optional),
            "error": str (if status="error")
        }
        """
        required = ["source", "status"]
        for field in required:
            if field not in message:
                return False, f"Missing required field: {field}"
        
        if message["status"] not in ["success", "error"]:
            return False, f"Invalid status: {message['status']}"
        
        if message["status"] == "error" and "error" not in message:
            return False, "Missing 'error' field for error status"
        
        return True, None
    
    @staticmethod
    def validate_metadata_message(message: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate metadata_topic message structure.
        Uses MetadataSchema validation.
        """
        from .metadata_schema import MetadataSchema
        return MetadataSchema.validate_metadata(message)


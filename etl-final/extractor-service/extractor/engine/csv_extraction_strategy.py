"""
CSV Extraction Strategy

This module implements the ExtractionStrategy interface for CSV file extraction.
Uses pandas chunked reading to prevent memory overflow with large CSV files.

Design Principles:
- Stateless: No instance variables that change between calls
- Idempotent: Same input produces same output
- Memory-efficient: Uses chunked reading to handle large files
- Robust: Handles various CSV formats (encoding, delimiters, headers)

Requirements:
- FR-6: Idempotent Operations
- US-1: Idempotent ETL operations (AC 1.4: Pipeline state is externalized)
- NFR-1: Performance - Memory: O(batch_size) not O(total_rows)
"""

import pandas as pd
from typing import Dict, Any, Optional, List
import os
from datetime import datetime, timezone

try:
    from .extraction_strategy import (
        ExtractionStrategy,
        Batch,
        ExtractionConfig,
        ExtractionError,
        ValidationError
    )
except ImportError:  # pragma: no cover - compatibility with legacy direct imports
    from extraction_strategy import (  # type: ignore
        ExtractionStrategy,
        Batch,
        ExtractionConfig,
        ExtractionError,
        ValidationError
    )


class CSVExtractionStrategy(ExtractionStrategy):
    """
    Extraction strategy for CSV files using pandas chunked reading.
    
    This strategy extracts data from CSV files in batches to prevent memory
    overflow issues with large files. It supports various CSV formats and
    handles edge cases like different encodings, delimiters, and headers.
    
    Key Features:
    - Chunked reading: Reads CSV in configurable chunks
    - Memory efficient: Only loads one batch at a time
    - Idempotent: Same offset always returns same data
    - Robust: Handles encoding detection, delimiter detection
    - Stateless: No mutable instance state
    
    Connection Parameters:
        file_path (str): Path to the CSV file (required)
        encoding (str): File encoding (default: 'utf-8', auto-detect if fails)
        delimiter (str): CSV delimiter (default: ',')
        has_header (bool): Whether CSV has header row (default: True)
        skip_rows (int): Number of rows to skip at start (default: 0)
        
    Example:
        config = ExtractionConfig(
            source_id="customers_csv",
            source_type="csv",
            connection_params={
                "file_path": "/data/customers.csv",
                "encoding": "utf-8",
                "delimiter": ",",
                "has_header": True
            },
            batch_size=1000
        )
        
        strategy = CSVExtractionStrategy()
        batch = strategy.extract_batch(config, offset=0, limit=1000)
    """
    
    def extract_batch(
        self,
        config: ExtractionConfig,
        offset: int,
        limit: int
    ) -> Batch:
        """
        Extract a batch of rows from a CSV file.
        
        Uses pandas chunked reading to efficiently extract data starting from
        the given offset. The method is idempotent - calling with the same
        config and offset will always return the same data.
        
        Args:
            config: Configuration containing file_path and CSV parameters
            offset: Starting row position (0-indexed, after header if present)
            limit: Maximum number of rows to extract
            
        Returns:
            Batch object containing extracted rows and metadata
            
        Raises:
            ExtractionError: If file doesn't exist, can't be read, or parsing fails
            ValidationError: If data fails schema validation (if schema_contract provided)
        """
        # Validate configuration
        self.validate_config(config)
        self._validate_csv_config(config)
        
        # Extract connection parameters
        file_path = config.connection_params["file_path"]
        encoding = config.connection_params.get("encoding", "utf-8")
        delimiter = config.connection_params.get("delimiter", ",")
        has_header = config.connection_params.get("has_header", True)
        skip_rows = config.connection_params.get("skip_rows", 0)
        
        # Check file exists
        if not os.path.exists(file_path):
            raise ExtractionError(f"CSV file not found: {file_path}")
        
        # Get file metadata
        file_size = os.path.getsize(file_path)
        file_name = os.path.basename(file_path)
        
        # Estimate total rows for progress tracking (if at offset 0)
        estimated_total_rows = None
        if offset == 0 and config.progress_tracker:
            estimated_total_rows = self._estimate_total_rows(file_path, encoding, delimiter, has_header, skip_rows)
        
        try:
            rows_window = self._read_rows_window(
                file_path=file_path,
                encoding=encoding,
                delimiter=delimiter,
                has_header=has_header,
                skip_rows=skip_rows,
                offset=offset,
                limit=limit + 1,  # fetch one extra row to compute has_more
            )
            rows = rows_window[:limit]
            has_more = len(rows_window) > limit
            
            # Generate batch metadata
            batch_id = self.generate_batch_id(config.source_id, offset)
            extraction_timestamp = datetime.now(timezone.utc)
            
            # Enrich rows with lineage metadata (_batch_id, _source_id, _extracted_at)
            # This ensures every row can be traced back to its source and extraction batch
            enriched_rows = self.enrich_rows_with_lineage(
                rows=rows,
                batch_id=batch_id,
                source_id=config.source_id,
                extracted_at=extraction_timestamp
            )
            
            metadata = {
                "file_name": file_name,
                "file_size": file_size,
                "encoding": encoding,
                "delimiter": delimiter,
                "has_header": has_header,
                "extraction_timestamp": extraction_timestamp.isoformat(),
                "rows_extracted": len(enriched_rows)
            }
            
            # Validate against schema contract if provided
            # Note: Validate original rows before enrichment to check source schema
            if config.schema_contract and rows:
                self._validate_schema(rows, config.schema_contract)
            
            # Update progress tracking
            if config.progress_tracker:
                # Calculate cumulative rows extracted (offset + current batch)
                cumulative_rows = offset + len(enriched_rows)
                # Batches processed is based on offset (how many batches came before) + 1 (current)
                batches_processed = (offset // limit) + 1
                
                self._update_progress(
                    config=config,
                    rows_extracted=cumulative_rows,
                    batches_processed=batches_processed,
                    current_offset=offset + len(enriched_rows),
                    estimated_total_rows=estimated_total_rows
                )
            
            return Batch(
                rows=enriched_rows,
                batch_id=batch_id,
                source_id=config.source_id,
                offset=offset,
                total_rows=len(enriched_rows),
                has_more=has_more,
                metadata=metadata
            )
            
        except ValidationError:
            # Re-raise ValidationError without wrapping
            raise
        except pd.errors.EmptyDataError:
            # Empty CSV file or no data at this offset
            batch_id = self.generate_batch_id(config.source_id, offset)
            extraction_timestamp = datetime.now(timezone.utc)
            
            return Batch(
                rows=[],
                batch_id=batch_id,
                source_id=config.source_id,
                offset=offset,
                total_rows=0,
                has_more=False,
                metadata={
                    "file_name": file_name,
                    "file_size": file_size,
                    "extraction_timestamp": extraction_timestamp.isoformat(),
                    "rows_extracted": 0
                }
            )
        except Exception as e:
            raise ExtractionError(f"Failed to extract CSV data: {str(e)}")

    def iter_batches(
        self,
        config: ExtractionConfig,
        batch_size: Optional[int] = None,
    ):
        """
        Stream CSV batches in order using pandas chunksize.

        This avoids repeated file rescans for sequential extraction workloads.
        """
        self.validate_config(config)
        self._validate_csv_config(config)

        file_path = config.connection_params["file_path"]
        encoding = config.connection_params.get("encoding", "utf-8")
        delimiter = config.connection_params.get("delimiter", ",")
        has_header = config.connection_params.get("has_header", True)
        skip_rows = config.connection_params.get("skip_rows", 0)
        effective_batch_size = int(batch_size or config.batch_size or 1000)
        if effective_batch_size <= 0:
            raise ExtractionError("batch_size must be positive")

        if not os.path.exists(file_path):
            raise ExtractionError(f"CSV file not found: {file_path}")

        def _read_chunks(current_encoding: str):
            read_kwargs = {
                "encoding": current_encoding,
                "delimiter": delimiter,
                "engine": "python",
                "chunksize": effective_batch_size,
                "header": 0 if has_header else None,
            }
            if skip_rows > 0:
                read_kwargs["skiprows"] = skip_rows

            for chunk in pd.read_csv(file_path, **read_kwargs):
                rows = chunk.to_dict("records")
                if rows:
                    yield rows

        try:
            yield from _read_chunks(encoding)
        except UnicodeDecodeError:
            detected = self._detect_encoding(file_path)
            yield from _read_chunks(detected)
    
    def _validate_csv_config(self, config: ExtractionConfig) -> None:
        """
        Validate CSV-specific configuration parameters.
        
        Args:
            config: Configuration to validate
            
        Raises:
            ValueError: If CSV-specific parameters are invalid
        """
        # Check connection_params is not empty dict (base class checks for None)
        if not config.connection_params:
            raise ValueError("connection_params cannot be empty for CSV extraction")
        
        if "file_path" not in config.connection_params:
            raise ValueError("file_path is required in connection_params for CSV extraction")
        
        file_path = config.connection_params["file_path"]
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("file_path must be a non-empty string")
        
        # Validate optional parameters if provided
        if "encoding" in config.connection_params:
            encoding = config.connection_params["encoding"]
            if not isinstance(encoding, str):
                raise ValueError("encoding must be a string")
        
        if "delimiter" in config.connection_params:
            delimiter = config.connection_params["delimiter"]
            if not isinstance(delimiter, str) or len(delimiter) != 1:
                raise ValueError("delimiter must be a single character")
        
        if "has_header" in config.connection_params:
            has_header = config.connection_params["has_header"]
            if not isinstance(has_header, bool):
                raise ValueError("has_header must be a boolean")
        
        if "skip_rows" in config.connection_params:
            skip_rows = config.connection_params["skip_rows"]
            if not isinstance(skip_rows, int) or skip_rows < 0:
                raise ValueError("skip_rows must be a non-negative integer")
    
    def _detect_encoding(self, file_path: str) -> str:
        """
        Detect file encoding by trying common encodings.
        
        Args:
            file_path: Path to the CSV file
            
        Returns:
            Detected encoding string
            
        Raises:
            ExtractionError: If no encoding works
        """
        encodings = ['utf-8', 'latin-1', 'iso-8859-1', 'cp1252', 'utf-16']
        
        for encoding in encodings:
            try:
                with open(file_path, 'r', encoding=encoding) as f:
                    f.read(1024)  # Try to read first 1KB
                return encoding
            except (UnicodeDecodeError, UnicodeError):
                continue
        
        raise ExtractionError(f"Could not detect encoding for file: {file_path}")
    
    def _check_has_more_rows(
        self,
        file_path: str,
        encoding: str,
        delimiter: str,
        has_header: bool,
        skip_rows: int,
        offset: int,
        limit: int
    ) -> bool:
        """
        Check if there are more rows after the current batch.
        
        Args:
            file_path: Path to CSV file
            encoding: File encoding
            delimiter: CSV delimiter
            has_header: Whether CSV has header
            skip_rows: Number of rows to skip at start
            offset: Current offset
            limit: Current batch size
            
        Returns:
            True if more rows exist, False otherwise
        """
        try:
            next_rows = self._read_rows_window(
                file_path=file_path,
                encoding=encoding,
                delimiter=delimiter,
                has_header=has_header,
                skip_rows=skip_rows,
                offset=offset + limit,
                limit=1,
            )
            return len(next_rows) > 0
        except Exception:
            return False

    def _read_rows_window(
        self,
        file_path: str,
        encoding: str,
        delimiter: str,
        has_header: bool,
        skip_rows: int,
        offset: int,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """
        Stream CSV rows and return a bounded window without skiprows-set growth.
        """
        if limit <= 0:
            return []

        def _stream_rows(current_encoding: str) -> List[Dict[str, Any]]:
            read_kwargs = {
                "encoding": current_encoding,
                "delimiter": delimiter,
                "engine": "python",
                "chunksize": max(1, min(5000, limit)),
            }
            if has_header:
                read_kwargs["header"] = 0
                read_kwargs["skiprows"] = skip_rows if skip_rows > 0 else None
            else:
                read_kwargs["header"] = None
                read_kwargs["skiprows"] = skip_rows if skip_rows > 0 else None

            rows_window: List[Dict[str, Any]] = []
            consumed = 0

            for chunk in pd.read_csv(file_path, **read_kwargs):
                chunk_rows = chunk.to_dict("records")
                if consumed + len(chunk_rows) <= offset:
                    consumed += len(chunk_rows)
                    continue

                start_idx = max(0, offset - consumed)
                for row in chunk_rows[start_idx:]:
                    rows_window.append(row)
                    if len(rows_window) >= limit:
                        return rows_window
                consumed += len(chunk_rows)

            return rows_window

        try:
            return _stream_rows(encoding)
        except UnicodeDecodeError:
            detected = self._detect_encoding(file_path)
            return _stream_rows(detected)
    
    def _validate_schema(self, rows: list[Dict[str, Any]], schema_contract: Dict[str, Any]) -> None:
        """
        Validate a sample row against the schema contract.
        
        This is a basic validation that checks if required fields exist.
        More sophisticated validation can be added based on schema_contract structure.
        
        Args:
            rows: Rows from the extracted batch
            schema_contract: Schema contract to validate against
            
        Raises:
            ValidationError: If validation fails
        """
        if "fields" in schema_contract:
            required_fields = [
                field["name"] 
                for field in schema_contract["fields"] 
                if field.get("required", False)
            ]
            
            for idx, row in enumerate(rows):
                missing_fields = []
                for field in required_fields:
                    value = row.get(field) if field in row else None
                    if field not in row or value is None or value == "" or value != value:
                        missing_fields.append(field)
                if missing_fields:
                    raise ValidationError(
                        f"Missing required fields in CSV row {idx}: {', '.join(missing_fields)}"
                    )
    
    def _estimate_total_rows(
        self,
        file_path: str,
        encoding: str,
        delimiter: str,
        has_header: bool,
        skip_rows: int
    ) -> Optional[int]:
        """
        Estimate total number of rows in CSV file for progress tracking.
        
        Uses a fast line counting approach rather than loading the entire file.
        
        Args:
            file_path: Path to CSV file
            encoding: File encoding
            delimiter: CSV delimiter
            has_header: Whether CSV has header
            skip_rows: Number of rows to skip at start
            
        Returns:
            Estimated total rows or None if estimation fails
        """
        try:
            # Fast line counting
            with open(file_path, 'r', encoding=encoding) as f:
                total_lines = sum(1 for _ in f)
            
            # Subtract header and skip rows
            data_rows = total_lines - skip_rows
            if has_header:
                data_rows -= 1
            
            return max(0, data_rows)
        except Exception:
            # If estimation fails, return None
            return None
